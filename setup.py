# -*- coding: utf-8 -*-
from curl_cffi import requests
from fake_useragent import FakeUserAgent
from datetime import datetime
from colorama import *
import asyncio, json, os, pytz, time
from typing import Optional, Dict, List

# 初始化终端颜色
init(autoreset=True)
wib = pytz.timezone('Asia/Jakarta')


class Nodepay:
    # -------------------- 基本配置 --------------------
    SOLVER_SERVER = "这里填写打码信息"          # 打码服务端
    BASE_API = "https://api.nodepay.ai/api"               # Nodepay 后端
    PAGE_URL = "https://app.nodepay.ai"                   # Turnstile 所在页面
    SITE_KEY = "0x4AAAAAAAx1CyDNL8zOEPe7"                 # Turnstile sitekey
    # --------------------------------------------------
    SAVE_TOKENS = False  # set True if you want to persist tokens.json

    def __init__(self) -> None:
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://app.nodepay.ai",
            "Referer": "https://app.nodepay.ai/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": FakeUserAgent().random
        }
        self.proxies: List[str] = []
        self.proxy_index = 0
        self.account_proxies: Dict[str, str] = {}
        self.captcha_tokens: Dict[str, str] = {}
        self.password: Dict[str, str] = {}

    # -------------------- 辅助输出 --------------------
    def log(self, msg: str, color=Fore.WHITE):
        print(
            f"{Fore.CYAN + Style.BRIGHT}[ {datetime.now().astimezone(wib).strftime('%x %X %Z')} ]{Style.RESET_ALL}"
            f"{Fore.WHITE} | {Style.RESET_ALL}{color}{msg}{Style.RESET_ALL}",
            flush=True
        )

    def mask_email(self, email: str) -> str:
        if '@' not in email:
            return email
        local, domain = email.split('@', 1)
        return f"{local[:3]}***{local[-3:]}@{domain}"

    # -------------------- 文件加载 --------------------
    def load_json_list(self, filename: str) -> List[dict]:
        if not os.path.exists(filename):
            self.log(f"File {filename} not found", Fore.RED)
            return []
        try:
            with open(filename, "r") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            self.log(f"{filename} invalid json", Fore.RED)
            return []

    def save_tokens(self, new_items: List[dict]):
        fn = "tokens.json"
        items = self.load_json_list(fn)
        items_map = {d["Email"]: d for d in items}
        for it in new_items:
            items_map[it["Email"]] = it
        with open(fn, "w") as f:
            json.dump(list(items_map.values()), f, indent=4)
        self.log("Tokens saved", Fore.GREEN)

    # -------------------- 代理 --------------------
    async def load_proxies(self, mode: int):
        fn = "proxy.txt"
        if mode == 1:  # 免费 ProxyScrape
            url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
            resp = await asyncio.to_thread(requests.get, url)
            text = resp.text
            with open(fn, "w") as f:
                f.write(text)
            self.proxies = [p.strip() for p in text.splitlines() if p.strip()]
        else:  # 私有或本地文件
            self.proxies = [p.strip() for p in open(fn).read().splitlines() if p.strip()] if os.path.exists(fn) else []
        self.log(f"Proxies loaded: {len(self.proxies)}")

    def next_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        if not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
            proxy = "http://" + proxy
        return proxy

    # -------------------- Turnstile 打码 --------------------
    async def solve_turnstile(self, proxy: Optional[str]) -> Optional[str]:
        try:
            # 1. 触发任务
            r = await asyncio.to_thread(
                requests.get,
                f"{self.SOLVER_SERVER}/turnstile",
                params={"url": self.PAGE_URL, "sitekey": self.SITE_KEY},
                proxy=proxy,
                timeout=30,
                verify=False,
                
            )
            if r.status_code != 202:
                self.log(f"solver error {r.status_code}: {r.text}", Fore.RED)
                return None
            task_id = r.json().get("task_id")
            if not task_id:
                self.log("solver response missing task_id", Fore.RED)
                return None
            # 2. 轮询结果
            start = time.time()
            while True:
                res = await asyncio.to_thread(
                    requests.get,
                    f"{self.SOLVER_SERVER}/result",
                    params={"id": task_id},
                    proxy=proxy,
                    timeout=20,
                    verify=False,
                    
                )
                if res.status_code in (200, 422):
                    try:
                        data = res.json()
                        val = data.get("value") if isinstance(data, dict) else None
                        if val and val != "CAPTCHA_FAIL":
                            return val
                    except ValueError:
                        body = res.text.strip()
                        if body == "CAPTCHA_NOT_READY":
                            pass  # continue polling
                        else:
                            self.log(f"poll unexpected body: {body[:100]}", Fore.RED)
                            return None
                if time.time() - start > 90:
                    self.log("solver timeout", Fore.RED)
                    return None
                await asyncio.sleep(3)
        except Exception as exc:
            self.log(f"solver exception {exc}", Fore.RED)
            return None

    # -------------------- 登录 --------------------
    async def login(self, email: str, token: str, proxy: Optional[str]) -> bool:
        url = f"{self.BASE_API}/auth/login?"
        data = json.dumps({
            "user": email, "password": self.password[email],
            "remember_me": True, "recaptcha_token": token
        })
        headers = {**self.headers, "Content-Type": "application/json", "Content-Length": str(len(data))}
        try:
            r = await asyncio.to_thread(
                requests.post, url, headers=headers, data=data,
                proxy=proxy, timeout=20, verify=False
            )
            r.raise_for_status()
            ok = r.json().get("msg") == "Success"
            if ok:
                np_token = r.json()["data"]["token"]
                if self.SAVE_TOKENS:
                    self.save_tokens([{"Email": email, "npToken": np_token}])
            return ok
        except Exception as exc:
            self.log(f"login error {exc}", Fore.RED)
            return False

    # -------------------- 主流程 --------------------
    async def run_account(self, idx: int, total: int, email: str, pwd: str, use_proxy: bool):
        self.log(f"{'='*20}[ {idx}/{total} ]{'='*20}", Fore.CYAN)
        self.log(f"Account: {self.mask_email(email)}")
        proxy = self.next_proxy() if use_proxy else None
        if proxy:
            self.log(f"Proxy  : {proxy}")

        token = await self.solve_turnstile(proxy)
        if not token:
            self.log("Captcha unsolved", Fore.RED)
            return
        self.log("Captcha solved", Fore.GREEN)

        if await self.login(email, token, proxy):
            self.log("Login success & token saved", Fore.GREEN)
        else:
            self.log("Login failed", Fore.RED)

    async def main(self):
        accounts = self.load_json_list("accounts.json")
        if not accounts:
            self.log("No accounts loaded", Fore.RED)
            return

        # 代理选项
        print("1. Free ProxyScrape | 2. Private proxy.txt | 3. No proxy")
        mode = int(input("Choose [1/2/3]: ").strip() or "3")
        use_proxy = mode in (1, 2)
        if use_proxy:
            await self.load_proxies(mode)

        # 运行所有账户
        for idx, acc in enumerate(accounts, 1):
            email, pwd = acc.get("Email"), acc.get("Password")
            if not email or not pwd or "@" not in email:
                self.log("Invalid account data skipped", Fore.RED)
                continue
            self.password[email] = pwd
            await self.run_account(idx, len(accounts), email, pwd, use_proxy)
            await asyncio.sleep(2)

        self.log("All done", Fore.CYAN)


if __name__ == "__main__":
    try:
        asyncio.run(Nodepay().main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
