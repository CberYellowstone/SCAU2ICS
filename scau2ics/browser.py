"""
浏览器管理器模块 - 提供浏览器实例的管理和复用
使用专用线程处理所有Playwright操作，避免线程切换问题
"""

import atexit
import queue
import threading
import time
import traceback

from scau2ics.config import DISABLE_BROWSER, logger

# 只在浏览器模式启用时导入playwright
if not DISABLE_BROWSER:
    try:
        from playwright.sync_api import Page, sync_playwright
    except ImportError:
        # 如果无法导入playwright，但浏览器模式被禁用，仍然可以继续
        logger.warning("无法导入playwright模块，但浏览器模式已被禁用，将仅使用缓存模式")
else:
    # 如果浏览器模式被禁用，确保playwright模块不被导入
    logger.info("浏览器模式已禁用，将不会导入playwright模块")

    class Page:  # type: ignore[no-redef]
        pass


class BrowserThread(threading.Thread):
    """专用浏览器线程，处理所有Playwright操作"""

    def __init__(self):
        super().__init__(daemon=True)
        self.task_queue = queue.Queue()
        self.result_map = {}
        self.result_lock = threading.Lock()
        self.next_task_id = 0
        self.id_lock = threading.Lock()
        self.playwright = None
        self.browser = None
        self.context = None
        self.last_activity = time.time()
        self.running = True
        self.timeout = 300  # 浏览器空闲5分钟后自动关闭

        logger.info("浏览器线程已创建")

    def run(self):
        """线程主循环，处理队列中的任务"""
        logger.info(f"浏览器线程启动 (线程ID: {threading.get_ident()})")

        try:
            # 初始化Playwright
            self.playwright = sync_playwright().start()
            self.browser = None
            self.context = None

            while self.running:
                try:
                    # 从队列获取任务，最多等待10秒
                    task = self.task_queue.get(timeout=10)

                    # 处理关闭命令
                    if task[0] == "STOP":
                        logger.info("浏览器线程收到停止命令")
                        self.close_resources()
                        self.running = False
                        break

                    # 解析任务
                    task_id, func, args, kwargs = task

                    # 执行任务
                    try:
                        result = func(*args, **kwargs)
                        with self.result_lock:
                            self.result_map[task_id] = (True, result)
                    except Exception as e:
                        logger.error(
                            f"浏览器线程执行任务出错: {str(e)}\n{traceback.format_exc()}"
                        )
                        with self.result_lock:
                            self.result_map[task_id] = (False, str(e))

                    # 标记任务完成
                    self.task_queue.task_done()
                    self.last_activity = time.time()

                except queue.Empty:
                    # 检查是否需要关闭浏览器以释放资源
                    if self.browser and time.time() - self.last_activity > self.timeout:
                        logger.info(f"浏览器空闲超过{self.timeout}秒，关闭以释放资源")
                        self.close_browser()
                except Exception as e:
                    logger.error(
                        f"浏览器线程循环出错: {str(e)}\n{traceback.format_exc()}"
                    )
        except Exception as e:
            logger.error(f"浏览器线程崩溃: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.close_resources()
            logger.info("浏览器线程退出")

    def ensure_browser(self):
        """确保浏览器实例和上下文存在且有效"""
        if not self.browser:
            logger.info("初始化浏览器实例")
            self.browser = self.playwright.firefox.launch(headless=True)
            self.context = None

        if not self.context:
            logger.info("创建浏览器上下文")
            self.context = self.browser.new_context()

        self.last_activity = time.time()

    def close_browser(self):
        """关闭浏览器实例，但保留Playwright"""
        if self.context:
            try:
                self.context.close()
            except Exception as e:
                logger.error(f"关闭浏览器上下文失败: {str(e)}")
            finally:
                self.context = None

        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                logger.error(f"关闭浏览器失败: {str(e)}")
            finally:
                self.browser = None

    def close_resources(self):
        """关闭所有资源"""
        self.close_browser()

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                logger.error(f"停止Playwright失败: {str(e)}")
            finally:
                self.playwright = None

    def get_clean_page(self) -> Page:
        """获取一个干净的页面，清除所有cookie和存储"""
        self.ensure_browser()

        # 清除所有cookie和存储
        try:
            if self.context:
                self.context.clear_cookies()
                self.context.clear_permissions()

                # 关闭所有现有页面
                for page in self.context.pages:
                    try:
                        page.evaluate(
                            "() => { localStorage.clear(); sessionStorage.clear(); }"
                        )
                        page.close()
                    except Exception as e:
                        logger.warning(f"清除页面存储失败: {str(e)}")
        except Exception as e:
            logger.warning(f"清除浏览器状态失败: {str(e)}")
            # 如果清除失败，重新创建上下文
            try:
                if self.context:
                    self.context.close()
            except Exception:
                pass
            self.context = None
            self.ensure_browser()

        # 确保context存在
        if not self.context:
            if self.browser is None:
                logger.error("浏览器实例为None，无法创建上下文")
                raise RuntimeError("浏览器初始化失败")
            self.context = self.browser.new_context()

        # 创建新页面
        return self.context.new_page()

    def next_id(self) -> int:
        """生成下一个任务ID"""
        with self.id_lock:
            task_id = self.next_task_id
            self.next_task_id += 1
            return task_id


class BrowserManager:
    """浏览器管理器，使用专用线程处理所有Playwright操作"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式实现"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BrowserManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """初始化浏览器管理器"""
        if getattr(self, "_initialized", False):
            return

        self._browser_thread = BrowserThread()
        self._browser_thread.start()
        self._initialized = True

        # 注册应用退出时的清理函数
        atexit.register(self.shutdown)
        logger.info("浏览器管理器已初始化")

    def execute_in_browser_thread(self, func, *args, **kwargs):
        """
        在浏览器线程中执行函数

        Args:
            func: 要执行的函数
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            函数的返回值

        Raises:
            Exception: 如果函数执行出错
        """
        if not self._browser_thread.is_alive():
            logger.warning("浏览器线程已停止，尝试重新启动")
            self._browser_thread = BrowserThread()
            self._browser_thread.start()

        # 创建任务ID并将任务添加到队列
        task_id = self._browser_thread.next_id()
        self._browser_thread.task_queue.put((task_id, func, args, kwargs))

        # 等待结果
        while True:
            with self._browser_thread.result_lock:
                if task_id in self._browser_thread.result_map:
                    success, result = self._browser_thread.result_map[task_id]
                    del self._browser_thread.result_map[task_id]
                    if success:
                        return result
                    else:
                        raise Exception(f"浏览器操作失败: {result}")

            # 短暂睡眠，避免CPU过度使用
            time.sleep(0.01)

    def get_page(self):
        """
        获取一个新的浏览器页面的闭包函数

        Returns:
            function: 执行登录并返回cookie的函数
        """

        def _get_page_and_cookies(url, username, password):
            page = self._browser_thread.get_clean_page()
            try:
                # 访问登录页面
                page.goto(url, wait_until="domcontentloaded")

                # 填写统一身份认证用户名和密码
                page.locator('//*[@id="username"]').fill(username)
                page.locator('//*[@id="password"]').fill(password)

                # 点击登录按钮
                page.locator(
                    "html body#cas div#container div#content div.loginWrap div.w1000 "
                    "div#flip.loginBox div#login.box form#fm1 div.row.btn-row input.btn-submit"
                ).click()

                # 等待重定向完成，检测到验证码输入框表示登录成功
                page.wait_for_selector(
                    "html body div#app.qz-login div.main div.wrap div.content form.el-form.login-form "
                    "div.el-form-item.captcha-item.is-required div.el-form-item__content img"
                )

                # 获取cookies
                cookies = page.context.cookies()
                cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookies}
                session_value = cookies[-1]["value"]

                return {"cookies": cookie_dict, "session": session_value}
            finally:
                # 关闭页面
                page.close()

        return _get_page_and_cookies

    def perform_sso_login(self, url, username, password):
        """
        执行SSO登录并返回cookies

        Args:
            url: 登录URL
            username: 用户名
            password: 密码

        Returns:
            tuple: (session, cookies)
        """
        if DISABLE_BROWSER:
            logger.warning("浏览器模式已禁用，无法执行SSO登录")
            return None, {}

        result = self.execute_in_browser_thread(
            self.get_page(), url, username, password
        )
        return result["session"], result["cookies"]

    def shutdown(self):
        """关闭浏览器管理器"""
        logger.info("关闭浏览器管理器")
        if hasattr(self, "_browser_thread"):
            self._browser_thread.task_queue.put(("STOP",))
            self._browser_thread.join(timeout=5.0)


# 全局单例实例
browser_manager = None


def get_browser_manager() -> BrowserManager:
    """获取浏览器管理器的全局实例"""
    global browser_manager
    if browser_manager is None:
        browser_manager = BrowserManager()
    return browser_manager
