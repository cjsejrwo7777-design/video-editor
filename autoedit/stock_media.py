"""Pexels 무료 스톡 사진 자동 검색/다운로드.

대본 줄(한국어)을 영어로 번역한 뒤 Pexels에서 검색어로 써서 사진을 찾는다.
Pexels 검색 색인이 주로 영어 기준이라 번역 없이 한국어로 검색하면
결과가 잘 안 나오는 경우가 많다.

무료 API 키 발급: https://www.pexels.com/api/ (가입만 하면 되고 결제는 없음)
"""
from __future__ import annotations

import os

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def translate_to_query(text: str) -> str:
    """한국어 대본 줄을 Pexels 검색에 적합한 영어 키워드로 번역한다."""
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="ko", target="en").translate(text) or text
    except Exception:
        return text


def search_photo_url(query: str, api_key: str, orientation: str) -> str | None:
    import requests

    resp = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 1, "orientation": orientation},
        timeout=15,
    )
    if resp.status_code == 401:
        raise ValueError("Pexels API 키가 올바르지 않습니다. 키를 다시 확인해주세요.")
    resp.raise_for_status()
    photos = resp.json().get("photos") or []
    if not photos:
        return None
    return photos[0]["src"]["large2x"]


def download_file(url: str, dest_path: str) -> None:
    import requests

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def fetch_stock_photo(line_text: str, api_key: str, dest_path: str, orientation: str = "portrait") -> bool:
    """대본 한 줄에 맞는 스톡 사진을 검색해서 dest_path에 저장한다. 찾으면 True."""
    query = translate_to_query(line_text)
    url = search_photo_url(query, api_key, orientation)
    if not url:
        return False
    download_file(url, dest_path)
    return True
