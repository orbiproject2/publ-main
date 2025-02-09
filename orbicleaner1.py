import tkinter as tk
from tkinter import ttk, messagebox
import logging
import getpass
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, UnexpectedAlertPresentException,
    NoSuchElementException
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# -------------------- 공통 유틸 함수 --------------------

def wait_for_element(driver, by, value, timeout=30):
    """
    Wait for an element to be located and return it.
    """
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
    except TimeoutException:
        logging.error(f"Element with {by} = {value} not found within {timeout} seconds.")
        return None


def handle_alert(driver, timeout=5):
    """
    Handles an alert if it appears within the specified timeout period.
    """
    try:
        alert = WebDriverWait(driver, timeout).until(EC.alert_is_present())
        logging.info(f"Alert detected: {alert.text}")
        alert.accept()
        logging.info("Alert accepted.")
        return True
    except TimeoutException:
        logging.info("No alert appeared.")
        return False


def delete_post(driver, post_number):
    """
    Navigate to a post's modify page and delete the post.
    Handle confirmation alerts if they appear.
    """
    try:
        logging.info(f"Attempting to delete post: {post_number}")
        driver.get(f"https://orbi.kr/modify/{post_number}")

        delete_btn = wait_for_element(driver, By.CLASS_NAME, "button.delete")
        if not delete_btn:
            logging.error(f"Delete button not found for post {post_number}.")
            return

        delete_btn.click()
        # 오르비에서 실제 삭제 확인 알럿이 뜨면 처리
        if handle_alert(driver):
            logging.info(f"Post {post_number} deletion confirmed.")
        else:
            logging.warning("No confirmation alert appeared. Deletion may not have been confirmed.")

    except Exception as e:
        logging.error(f"Failed to delete post {post_number}: {e}")


def extract_posts(driver):
    """
    Extract all posts from the user's post list,
    skipping '회원에 의해 삭제된 글입니다.'

    - If a page has no valid posts, we still try the next page,
      because Orbi might have valid posts on later pages.
    - We only stop if we cannot load the page or can't find 'post-list',
      or if a 'no such element' error occurs (i.e. p.title not found).
    """
    posts = []
    page = 1

    while True:
        logging.info(f"Processing page {page}...")
        try:
            driver.get(f"https://orbi.kr/my/post?page={page}")
        except Exception as e:
            logging.error(f"Error occurred while loading page {page}: {e}")
            logging.info("Stopping pagination due to page load error.")
            break

        # post-list 없으면 중단
        if not wait_for_element(driver, By.CLASS_NAME, "post-list", timeout=10):
            logging.error(f"Post list not found on page {page}. Stopping pagination.")
            break

        post_elements = driver.find_elements(By.CSS_SELECTOR, "ul.post-list > li")
        if not post_elements:
            logging.info(f"No posts found on page {page}. Checking the next page anyway...")

        for post in post_elements:
            try:
                # p.title → div.title 등으로 변경 필요할 수 있음
                title_element = post.find_element(By.CSS_SELECTOR, "p.title")
                title = title_element.text.strip() if title_element.text.strip() else None

                href = (
                    post.find_element(By.TAG_NAME, "a").get_attribute("href").split("/")[-1]
                    if post.find_element(By.TAG_NAME, "a").get_attribute("href")
                    else None
                )

                # "회원에 의해 삭제된 글입니다."는 제외
                if title == "회원에 의해 삭제된 글입니다.":
                    continue

                if title and href:
                    posts.append({"title": title, "href": href})

            except NoSuchElementException as e:
                logging.warning("Failed to extract post details (NoSuchElementException). Stopping pagination.")
                logging.warning(f"Detail: {e}")
                return posts
            except Exception as e:
                logging.warning(f"Failed to extract post details: {e}")

        page += 1

    return posts


# -------------------- 메인 GUI --------------------

def run_gui():
    root = tk.Tk()
    root.title("오르비 글 선택 삭제기 (GUI)")
    root.geometry("600x700")

    # 1) 로그인 프레임
    login_frame = tk.Frame(root, padx=10, pady=10)
    login_frame.pack(fill="x")

    tk.Label(login_frame, text="오르비 아이디").pack()
    username_entry = tk.Entry(login_frame)
    username_entry.pack(pady=5, fill="x")

    tk.Label(login_frame, text="비밀번호").pack()
    password_entry = tk.Entry(login_frame, show="*")
    password_entry.pack(pady=5, fill="x")

    login_button = ttk.Button(login_frame, text="로그인")
    login_button.pack(pady=10)

    # 2) 결과(글 목록) 프레임
    result_frame = tk.Frame(root, padx=10, pady=10)

    # 스크롤 가능한 캔버스 + 내부 프레임
    canvas = tk.Canvas(result_frame, width=550, height=400)
    canvas.pack(side=tk.LEFT, fill="both", expand=True)

    scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill="y")

    canvas.configure(yscrollcommand=scrollbar.set)
    # 내부 내용을 담을 frame
    posts_frame = tk.Frame(canvas)
    canvas.create_window((0, 0), window=posts_frame, anchor="nw")

    # 전체 선택/해제 체크박스
    select_all_var = tk.BooleanVar()
    select_all_cb = ttk.Checkbutton(posts_frame, text="모두 선택", variable=select_all_var)
    select_all_cb.pack(anchor="w", pady=5)

    # 선택한 글 삭제 버튼
    delete_button = ttk.Button(root, text="선택한 글 삭제하기")
    delete_button.pack(pady=10, side=tk.BOTTOM)

    # 체크박스 저장할 dict: index -> (BooleanVar, {title, href})
    post_checks = {}

    driver = None
    posts_data = []

    def on_select_all():
        # 모두 선택 / 해제 시 모든 체크박스를 갱신
        do_select = select_all_var.get()
        for idx, (var, info) in post_checks.items():
            var.set(do_select)

    def on_delete():
        # 삭제 버튼 클릭 시
        selected_posts = [
            info for idx, (var, info) in post_checks.items()
            if var.get()  # 체크된 항목만
        ]

        if not selected_posts:
            messagebox.showinfo("알림", "삭제할 글을 선택하세요.")
            return

        # 정말 삭제할 것인지 재확인
        confirm = messagebox.askyesno("확인", "정말로 선택한 글을 삭제하시겠습니까?")
        if not confirm:
            return

        # 실제 삭제 진행
        for post_info in selected_posts:
            delete_post(driver, post_info["href"])

        messagebox.showinfo("완료", "선택한 글을 삭제했습니다.")
        # 혹시 삭제 후 목록 갱신이 필요하다면, 아래처럼 재로딩 로직 추가 가능
        # (이 예시는 간단히 안내 메시지만 표시하고 끝냅니다.)

    def on_login():
        nonlocal driver, posts_data

        username = username_entry.get().strip()
        pw = password_entry.get().strip()
        if not username or not pw:
            messagebox.showerror("오류", "아이디와 비밀번호를 입력하세요.")
            return

        # WebDriver 초기화
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920x1080")

        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://login.orbi.kr/login")

            # 로그인 시도
            user_field = wait_for_element(driver, By.NAME, "username")
            if not user_field:
                messagebox.showerror("오류", "사용자명 입력란을 찾을 수 없습니다.")
                return
            user_field.send_keys(username)

            pw_field = wait_for_element(driver, By.NAME, "password")
            if not pw_field:
                messagebox.showerror("오류", "비밀번호 입력란을 찾을 수 없습니다.")
                return
            pw_field.send_keys(pw)
            pw_field.submit()

            # 로그인 성공 여부 확인
            if not wait_for_element(driver, By.CLASS_NAME, "post-list"):
                messagebox.showerror("오류", "로그인 실패 또는 게시글 목록을 찾을 수 없습니다.")
                return

            logging.info("Login successful!")

            posts_data = extract_posts(driver)
            if not posts_data:
                messagebox.showinfo("알림", "'회원에 의해 삭제된 글'을 제외하고는 게시글이 없습니다.")
                return

            # 로그인 프레임 숨기고 결과 프레임 표시
            login_frame.pack_forget()
            result_frame.pack(fill="both", expand=True)

            # 모두 선택 체크박스의 콜백 설정
            select_all_cb.config(command=on_select_all)

            # 글 목록 체크박스 생성
            for idx, post in enumerate(posts_data):
                var = tk.BooleanVar()
                c = ttk.Checkbutton(posts_frame, text=post["title"], variable=var)
                c.pack(anchor="w")

                post_checks[idx] = (var, post)

            # 스크롤 영역 크기를 갱신
            posts_frame.update_idletasks()
            canvas.config(scrollregion=canvas.bbox("all"))

        except Exception as e:
            logging.error(f"An error occurred during login or extraction: {e}")
            messagebox.showerror("오류", f"로그인/글 목록 처리 중 오류: {e}")

    # 버튼에 함수 바인딩
    login_button.config(command=on_login)
    delete_button.config(command=on_delete)

    root.mainloop()


if __name__ == "__main__":
    run_gui()
