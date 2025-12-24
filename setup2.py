# -*- coding: utf-8 -*-
from curl_cffi import requests
from fake_useragent import FakeUserAgent
from datetime import datetime
from colorama import *
import asyncio, json, os, pytz, time, random
from typing import Optional, Dict, List

# 初始化终端颜色
init(autoreset=True)
wib = pytz.timezone('Asia/Jakarta')


class Nodepay:
    # -------------------- 基本配置 --------------------
    SOLVER_SERVER = "http://127.0.0.1:500"          # 打码服务端
    BASE_API = "https://api.nodepay.ai/api"               # Nodepay 后端
    PAGE_URL = "https://app.nodepay.ai"                   # Turnstile 所在页面
    SITE_KEY = "0x4AAAAAAAx1CyDNL8zOEPe7"                 # Turnstile sitekey
    # --------------------------------------------------
    SAVE_TOKENS = True  # set True if you want to persist tokens.json

    def __init__(self) -> None:
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Origin": "https://app.nodepay.ai",
            "Pragma": "no-cache",
            "Referer": "https://app.nodepay.ai/",
            "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
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
            with open(filename, "r", encoding='utf-8') as f:
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
        with open(fn, "w", encoding='utf-8') as f:
            json.dump(list(items_map.values()), f, indent=4, ensure_ascii=False)
        self.log("Tokens saved", Fore.GREEN)

    # -------------------- 代理 --------------------
    async def load_proxies(self, mode: int):
        fn = "proxy.txt"
        if mode == 1:  # 免费 ProxyScrape
            url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
            resp = await asyncio.to_thread(requests.get, url)
            text = resp.text
            with open(fn, "w", encoding='utf-8') as f:
                f.write(text)
            self.proxies = [p.strip() for p in text.splitlines() if p.strip()]
        else:  # 私有或本地文件
            if os.path.exists(fn):
                with open(fn, "r", encoding='utf-8') as f:
                    self.proxies = [p.strip() for p in f.read().splitlines() if p.strip()]
        self.log(f"Proxies loaded: {len(self.proxies)}")

    def next_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        if not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
            proxy = "http://" + proxy
        return proxy

    # -------------------- 更新请求头 --------------------
    def update_headers(self):
        """更新请求头，增加随机性"""
        self.headers.update({
            "User-Agent": FakeUserAgent().random,
            "Accept-Language": random.choice([
                "en-US,en;q=0.9",
                "en-GB,en;q=0.9",
                "en;q=0.8,zh-CN;q=0.7,zh;q=0.6"
            ]),
            "Sec-Ch-Ua": f'"Not.A/Brand";v="8", "Chromium";v="{random.randint(100, 124)}", "Google Chrome";v="{random.randint(100, 124)}.0.0.0"',
            "Sec-Ch-Ua-Platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
            "Sec-Fetch-Dest": random.choice(["empty", "document", "script", "style", "image", "font"]),
        })

    # -------------------- Turnstile 打码 --------------------
    async def solve_turnstile(self, proxy: Optional[str]) -> Optional[str]:
        try:
            # 更新请求头
            self.update_headers()
            
            # 1. 触发任务
            r = await asyncio.to_thread(
                requests.get,
                f"{self.SOLVER_SERVER}/turnstile",
                params={"url": self.PAGE_URL, "sitekey": self.SITE_KEY},
                headers=self.headers,
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
            while time.time() - start < 90:  # 90秒超时
                # 更新请求头
                self.update_headers()
                
                res = await asyncio.to_thread(
                    requests.get,
                    f"{self.SOLVER_SERVER}/result",
                    params={"id": task_id},
                    headers=self.headers,
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
                        if body != "CAPTCHA_NOT_READY":
                            self.log(f"poll unexpected body: {body[:100]}", Fore.RED)
                            return None
                await asyncio.sleep(3)
            self.log("solver timeout", Fore.RED)
            return None
        except Exception as exc:
            self.log(f"solver exception {exc}", Fore.RED)
            return None

    # -------------------- 登录 --------------------
    async def login(self, email: str, token: str, proxy: Optional[str]) -> bool:
        url = f"{self.BASE_API}/auth/login?"
        
        # 更新请求头
        self.update_headers()
        headers = {
            **self.headers,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.nodepay.ai",
            "Referer": "https://app.nodepay.ai/login",
        }
        
        data = json.dumps({
            "user": email, 
            "password": self.password[email],
            "remember_me": True, 
            "recaptcha_token": token
        })
        
        try:
            r = await asyncio.to_thread(
                requests.post, 
                url, 
                headers=headers, 
                data=data,
                proxy=proxy, 
                timeout=30, 
                verify=False
            )
            
            if r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 60))
                self.log(f"Rate limited. Waiting {retry_after} seconds...", Fore.YELLOW)
                await asyncio.sleep(retry_after)
                return await self.login(email, token, proxy)  # 重试登录
                
            r.raise_for_status()
            ok = r.json().get("msg") == "Success"
            if ok:
                np_token = r.json().get("data", {}).get("token")
                if np_token and self.SAVE_TOKENS:
                    self.save_tokens([{"Email": email, "npToken": np_token}])
            return ok
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', 60))
                self.log(f"HTTP 429 - Rate limited. Waiting {retry_after} seconds...", Fore.YELLOW)
                await asyncio.sleep(retry_after)
                return await self.login(email, token, proxy)  # 重试登录
            self.log(f"HTTP Error {e.response.status_code}: {e.response.text}", Fore.RED)
            return False
        except Exception as exc:
            self.log(f"Login error: {str(exc)}", Fore.RED)
            return False

    # -------------------- 主流程 --------------------
    async def run_account(self, idx: int, total: int, email: str, pwd: str, use_proxy: bool):
        self.log(f"{'='*20}[ {idx}/{total} ]{'='*20}", Fore.CYAN)
        self.log(f"Account: {self.mask_email(email)}")
        
        # 随机延迟 5-15 秒
        delay = random.uniform(5, 15)
        self.log(f"Waiting {delay:.1f} seconds before starting...", Fore.YELLOW)
        await asyncio.sleep(delay)
        
        proxy = self.next_proxy() if use_proxy else None
        if proxy:
            self.log(f"Using proxy: {proxy}")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            self.log(f"Attempt {attempt}/{max_retries}")
            
            # 更新请求头
            self.update_headers()
            
            try:
                token = await self.solve_turnstile(proxy)
                if not token:
                    self.log("Captcha unsolved", Fore.RED)
                    continue
                self.log("Captcha solved", Fore.GREEN)

                if await self.login(email, token, proxy):
                    self.log("Login success & token saved", Fore.GREEN)
                    return True
                else:
                    self.log("Login failed", Fore.RED)
            except Exception as e:
                self.log(f"Error during attempt {attempt}: {str(e)}", Fore.RED)
            
            # 如果不是最后一次尝试，则等待
            if attempt < max_retries:
                wait_time = (2 ** attempt) + random.uniform(0, 1)  # 指数退避
                self.log(f"Waiting {wait_time:.1f} seconds before next attempt...", Fore.YELLOW)
                await asyncio.sleep(wait_time)
        
        self.log(f"All {max_retries} attempts failed for {self.mask_email(email)}", Fore.RED)
        return False

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
        success_count = 0
        for idx, acc in enumerate(accounts, 1):
            email, pwd = acc.get("Email"), acc.get("Password")
            if not email or not pwd or "@" not in email:
                self.log("Invalid account data skipped", Fore.RED)
                continue
            self.password[email] = pwd
            
            if await self.run_account(idx, len(accounts), email, pwd, use_proxy):
                success_count += 1
            
            # 账号之间随机等待
            if idx < len(accounts):
                wait = random.uniform(10, 30)
                self.log(f"Waiting {wait:.1f} seconds before next account...", Fore.YELLOW)
                await asyncio.sleep(wait)

        total = len(accounts)
        self.log(f"All done. Success: {success_count}/{total}", 
                Fore.GREEN if success_count == total else Fore.YELLOW)


if __name__ == "__main__":
    try:
        asyncio.run(Nodepay().main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")