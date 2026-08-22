"""
MegaCloud & RapidCloud Video Stream Extractor
Fixed and modernized for AniWatch, HiAnime, and RabbitStream embed providers.
"""

import re
import json
import base64
from typing import Dict, Any, Optional

try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False

# Safe proxy loader
try:
    from cantarella.core.proxy import get_random_proxy, get_proxy_dict
except ImportError:
    def get_random_proxy():
        return None
    def get_proxy_dict(proxy):
        if not proxy:
            return None
        return {"http": proxy, "https": proxy} if isinstance(proxy, str) else proxy


def hash_str(key: str) -> int:
    """Computes a 32-bit integer hash from a secret key."""
    key_value = 0
    for char in key:
        key_value = (key_value * 31 + ord(char)) & 0xFFFFFFFF
    return key_value


class Megacloud:
    """
    MegaCloud Stream Decryptor & Extractor.
    Extracts HLS m3u8 playlists, subtitle tracks (.vtt), and timestamps.
    """
    default_base_url = "https://megacloud.tv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, embed_url: str, custom_proxy: Optional[str] = None) -> None:
        self.embed_url = embed_url.strip()
        self.custom_proxy = custom_proxy

    def _extract_client_key(self, html: str) -> str:
        """
        Extracts the dynamic obfuscation key from MegaCloud embed HTML.
        Supports multiple versions of MegaCloud scripts.
        """
        # Pattern 1: 48-character hex/alphanumeric key
        match = re.search(r'([a-zA-Z0-9]{48})', html)
        if match:
            return match.group(1)

        # Pattern 2: Triplet variables x, y, z
        match_triplet = re.search(r'x:\s*"([a-zA-Z0-9]{16})",\s*y:\s*"([a-zA-Z0-9]{16})",\s*z:\s*"([a-zA-Z0-9]{16})"', html)
        if match_triplet:
            return "".join(match_triplet.groups())

        # Pattern 3: Dynamic window or local key variable
        match_var = re.search(r'(?:_k|client_key|token)\s*=\s*[\'"]([a-zA-Z0-9]{32,64})[\'"]', html)
        if match_var:
            return match_var.group(1)

        return ""

    def _lcg(self, n: int) -> int:
        """Linear Congruential Generator step."""
        return (n * 1103515245 + 12345) & 0x7FFFFFFF

    def _shuffle_sources(self, sources: list, key: str) -> list:
        """Unshuffles character blocks according to sorted key characters."""
        if not key or len(key) == 0 or len(sources) < len(key):
            return sources
        array_count = len(sources) // len(key)
        arrays = [[""] * len(key) for _ in range(array_count)]
        key_dict = {i: char for i, char in enumerate(key)}
        key_sorted = {i: char for i, char in sorted(key_dict.items(), key=lambda p: p[1])}
        p = 0
        for idx in key_sorted.keys():
            for arr_idx in range(array_count):
                if p < len(sources):
                    arrays[arr_idx][idx] = sources[p]
                    p += 1
        res = []
        for arr in arrays:
            res.extend(arr)
        return res

    def _process_sources(self, encrypted_data: str, key: str) -> str:
        """Applies inverse Caesar shift with LCG stream cipher and unscrambles."""
        sources = list(encrypted_data)
        current_hash = hash_str(key)
        new_sources = []
        for char in sources:
            current_hash = self._lcg(current_hash)
            val1 = ord(char) - 32
            val2 = current_hash % 95
            v = (val1 - val2 + 95 * 10) % 95 + 32
            new_sources.append(chr(v))
        shuffled = self._shuffle_sources(new_sources, key)
        return "".join(shuffled)

    def extract(self) -> Dict[str, Any]:
        """
        Extracts stream sources and subtitle tracks from the embed URL.
        """
        # Extract server ID from embed URL
        # Supports /embed-2/e-1/{id}, /e-1/{id}, /embed-4/e-1/{id}, or id=...
        sid_match = (
            re.search(r"e-1/([a-zA-Z0-9]+)", self.embed_url) or
            re.search(r"embed-\d+/([a-zA-Z0-9]+)", self.embed_url) or
            re.search(r"id=([a-zA-Z0-9]+)", self.embed_url)
        )
        if not sid_match:
            return {"sources": [], "tracks": [], "error": "Invalid embed URL: cannot find stream ID"}

        sid = sid_match.group(1)

        # Normalize domain to megacloud.tv or host domain
        base_match = re.search(r'(https?://[^/]+)', self.embed_url)
        base_domain = base_match.group(1) if base_match else self.default_base_url
        if "megacloud.blog" in base_domain:
            base_domain = "https://megacloud.tv"

        curr_embed_url = self.embed_url.replace(".blog", ".tv")

        # Configure session and proxies
        if HAS_CURL_CFFI:
            session = requests.Session()
        else:
            session = requests.Session()

        proxy = self.custom_proxy or get_random_proxy()
        proxy_dict = get_proxy_dict(proxy) if proxy else None
        if proxy_dict:
            session.proxies.update(proxy_dict)

        headers = self.headers.copy()
        headers["Referer"] = "https://hianime.ro/"
        headers["Origin"] = base_domain

        try:
            # 1. Fetch embed page HTML to extract client key
            get_kwargs = {"headers": headers, "timeout": 10}
            if HAS_CURL_CFFI:
                get_kwargs["impersonate"] = "chrome"

            resp_html = session.get(curr_embed_url, **get_kwargs).text
            client_key = self._extract_client_key(resp_html)

            # 2. Call getSources API endpoint
            # Endpoints: /embed-2/ajax/e-1/getSources (modern) or /embed-2/v3/e-1/getSources
            get_src_urls = [
                f"{base_domain}/embed-2/ajax/e-1/getSources",
                f"{base_domain}/embed-2/v3/e-1/getSources",
                f"{base_domain}/ajax/embed-4/getSources"
            ]

            resp_json = None
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Referer"] = curr_embed_url

            for api_url in get_src_urls:
                try:
                    params = {"id": sid}
                    if client_key:
                        params["_k"] = client_key

                    res = session.get(api_url, headers=headers, params=params, **({"impersonate": "chrome"} if HAS_CURL_CFFI else {"timeout": 10}))
                    if res.status_code == 200:
                        data = res.json()
                        if data and ("sources" in data or "encrypted" in str(data)):
                            resp_json = data
                            break
                except Exception:
                    continue

            if not resp_json:
                return {"sources": [], "tracks": [], "error": "Could not retrieve stream sources"}

            # 3. Decrypt sources if encrypted string
            sources = resp_json.get("sources")
            if isinstance(sources, str):
                try:
                    decrypted = self._process_sources(sources, client_key)
                    resp_json["sources"] = json.loads(decrypted)
                except Exception as dec_err:
                    print(f"Decryption error: {dec_err}")
                    # Try plain json in case it wasn't encrypted
                    try:
                        resp_json["sources"] = json.loads(sources)
                    except Exception:
                        pass

            if "sources" not in resp_json or not isinstance(resp_json["sources"], list):
                resp_json["sources"] = []
            if "tracks" not in resp_json:
                resp_json["tracks"] = []

            return resp_json

        except Exception as e:
            print(f"Megacloud extraction error: {e}")
            return {"sources": [], "tracks": [], "error": str(e)}


if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://megacloud.tv/embed-2/e-1/k4z8r2o9p1?k=1"
    print(f"Testing extraction for: {test_url}")
    extractor = Megacloud(test_url)
    result = extractor.extract()
    print(json.dumps(result, indent=2))
