#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import warnings
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# SSL警告を無視（自己署名証明書のため）
warnings.simplefilter('ignore', InsecureRequestWarning)

# 設定
BASE_URL = "https://www.marubeni.com"
TARGET_URL = "https://www.marubeni.com/jp/research/report/"
OUTPUT_FILE = "feed.xml"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# タグの日本語名を英語にマッピング（カテゴリ用）
TAG_MAP = {
    "政治経済": "Politics & Economy",
    "産業": "Industry",
    "世界": "Global",
    "米国": "United States",
    "日本": "Japan",
    "中国": "China",
    "欧州": "Europe",
    "アジア": "Asia",
    "中東": "Middle East",
}


def fetch_html(url):
    """HTMLを取得する（SSL検証を無効化）"""
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text
    except requests.RequestException as e:
        print(f"HTML取得エラー: {e}")
        return None


def parse_date(date_str):
    """日付文字列をパースする（例: 2026.09.03）"""
    try:
        year, month, day = map(int, date_str.split('.'))
        jst = timezone(timedelta(hours=9))
        dt = datetime(year, month, day, 0, 0, 0, tzinfo=jst)
        return dt.astimezone(timezone.utc)
    except Exception as e:
        print(f"日付パースエラー: {date_str} - {e}")
        return datetime.now(timezone.utc)


def extract_title_and_author(link_elem):
    """
    aタグからタイトルと著者を抽出する
    HTML構造:
    <a href="..." class="iconPdf">
      <span>
        タイトル行1
        タイトル行2（ある場合）
        <br>著者名
      </span>
      [1MB]
    </a>
    """
    title_span = link_elem.find('span')
    if not title_span:
        # spanがない場合はaタグのテキスト全体を使用
        full_text = link_elem.get_text(strip=True)
        # ファイルサイズ部分を除去
        full_text = re.sub(r'\[\d+MB\]$', '', full_text).strip()
        return full_text, ""

    # span内のHTMLを取得（<br>タグを含む）
    span_html = str(title_span)
    
    # <br>タグで分割
    parts = re.split(r'<br\s*/?>', span_html, flags=re.IGNORECASE)
    
    # 各パーツからHTMLタグを除去してテキストを抽出
    clean_parts = []
    for part in parts:
        # タグを除去
        clean = re.sub(r'<[^>]+>', '', part).strip()
        if clean:
            clean_parts.append(clean)
    
    if not clean_parts:
        return "無題", ""
    
    # 最後のパーツが著者名（スペースで区切られた名前、または「株式会社」で始まる場合）
    # または「丸紅」が含まれる場合も著者と判断
    if len(clean_parts) >= 2:
        last_part = clean_parts[-1]
        # 著者名のパターン: 「姓 名」または「姓 名，姓 名」など
        # または「株式会社丸紅」など
        if re.search(r'[^\s]+\s[^\s]+', last_part) or '丸紅' in last_part or '株式会社' in last_part:
            title = ' '.join(clean_parts[:-1])
            author = last_part
            return title, author
    
    # それ以外の場合はすべてタイトルとして扱う
    return ' '.join(clean_parts), ""


def extract_reports(html):
    """HTMLからレポート情報を抽出する"""
    soup = BeautifulSoup(html, 'html.parser')
    reports = []

    # すべてのニュースリスト（月ごと）を取得
    news_lists = soup.find_all('div', class_='newsList')

    for news_list in news_lists:
        items = news_list.find_all('li')

        for item in items:
            try:
                # 日付を取得
                date_elem = item.find('span', class_='date')
                if not date_elem:
                    continue
                date_str = date_elem.get_text(strip=True)

                # リンクとタイトルを取得
                link_elem = item.find('a', class_='iconPdf')
                if not link_elem:
                    continue

                href = link_elem.get('href', '')
                full_url = urljoin(BASE_URL, href)

                # タイトルと著者を抽出
                title, author = extract_title_and_author(link_elem)
                
                # タイトルが長すぎる場合は短縮
                if len(title) > 200:
                    title = title[:197] + "..."

                # タグを取得
                tags = []
                tag_wrap = item.find('div', class_='tagWrap')
                if tag_wrap:
                    tag_spans = tag_wrap.find_all('span', class_='tag')
                    for tag_span in tag_spans:
                        tag_text = tag_span.get_text(strip=True)
                        if tag_text:
                            tags.append(tag_text)

                # ファイルサイズを取得
                file_size_match = re.search(r'\[([^\]]+)\]', link_elem.get_text())
                file_size = file_size_match.group(1) if file_size_match else ""

                # 説明文を作成
                description_parts = []
                if tags:
                    description_parts.append(f"タグ: {', '.join(tags)}")
                if author:
                    description_parts.append(f"著者: {author}")
                if file_size:
                    description_parts.append(f"ファイルサイズ: {file_size}")

                description = "\n".join(description_parts)

                report = {
                    'title': title,
                    'link': full_url,
                    'pubDate': parse_date(date_str),
                    'description': description,
                    'author': author,
                    'tags': tags,
                    'date_str': date_str,
                    'file_size': file_size,
                }
                reports.append(report)

            except Exception as e:
                print(f"レポート抽出中にエラー: {e}")
                continue

    # 日付の新しい順にソート
    reports.sort(key=lambda x: x['pubDate'], reverse=True)

    return reports


def generate_rss(reports):
    """RSSフィードを生成する"""
    fg = FeedGenerator()
    fg.title("丸紅経済研究所 レポート")
    fg.description("丸紅経済研究所のレポート一覧（RSSフィード）")
    fg.link(href=TARGET_URL, rel='alternate')
    # ★ ここを自分のGitHubユーザー名に変更してください ★
    fg.link(href='https://raw.githubusercontent.com/marinemp3/marubeni-report-rss/main/feed.xml', rel='self')
    fg.language('ja')
    fg.lastBuildDate(datetime.now(timezone.utc))
    fg.generator('FeedGenerator')

    for report in reports[:100]:
        fe = fg.add_entry()
        fe.title(report['title'])
        fe.link(href=report['link'])
        fe.guid(report['link'], permalink=True)
        fe.pubDate(report['pubDate'])

        desc = report['description']
        fe.description(desc)

        for tag in report['tags']:
            tag_en = TAG_MAP.get(tag, tag)
            fe.category(term=tag_en, label=tag)

    rss_str = fg.rss_str(pretty=True)
    with open(OUTPUT_FILE, 'wb') as f:
        f.write(rss_str)

    print(f"RSSフィードを生成しました: {OUTPUT_FILE}")
    print(f"件数: {len(reports[:100])} 件")


def main():
    print(f"[ステッカー] 丸紅経済研究所レポートRSS生成開始")
    print(f"[ステッカー] 対象URL: {TARGET_URL}")

    html = fetch_html(TARGET_URL)
    if not html:
        print("[ステッカー] HTMLの取得に失敗しました")
        return 1

    reports = extract_reports(html)
    print(f"[ステッカー] 抽出件数: {len(reports)} 件")

    if not reports:
        print("[ステッカー] レポートが見つかりませんでした")
        return 1

    generate_rss(reports)
    print("[ステッカー] 完了しました")
    return 0


if __name__ == "__main__":
    exit(main())
