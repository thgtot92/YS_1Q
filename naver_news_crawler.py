import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import datetime
import pytz

def fetch_news_titles(query: str, date_yyyymmdd: str, page_limit: int = 3):
    encoded = quote(query)
    nso = f"so:dd,p:from{date_yyyymmdd}to{date_yyyymmdd}"
    headers = {"User-Agent": "Mozilla/5.0"}
    all_news = []

    base_time = datetime.datetime.strptime(date_yyyymmdd, "%Y%m%d").replace(hour=9)
    for page in range(1, page_limit + 1):
        start = (page - 1) * 10 + 1
        url = f"https://search.naver.com/search.naver?where=news&query={encoded}&nso={nso}&start={start}"
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')

        for tag in soup.select("a.news_tit"):
            title = tag.get("title", "").strip()
            link = tag.get("href", "").strip()
            if title and link:
                all_news.append({
                    "title": title,
                    "url": link,
                    "pub_date": base_time,  # 핵심 수정
                    "sentiment": "unknown"
                })

    return all_news


def match_news_before_events(news_list, event_df):
    """
    각 이벤트 시점보다 과거에 발생한 뉴스만 연결해 리턴 (타임존 일치 포함)

    Args:
        news_list (List[Dict]): 전체 뉴스 데이터 (title, pub_date 포함, datetime 객체)
        event_df (DataFrame): 이벤트 시점 목록 (datetime 컬럼 포함)

    Returns:
        Dict[datetime: List[뉴스]]
    """
    matched_results = {}
    korea_tz = pytz.timezone("Asia/Seoul")

    # 이벤트 datetime 컬럼 전체를 KST로 일괄 변환
    if event_df["datetime"].dt.tz is None:
        event_df["datetime"] = event_df["datetime"].apply(lambda x: korea_tz.localize(x))

    for _, event_row in event_df.iterrows():
        event_time = event_row["datetime"]

        matched_news = []

        for news in news_list:
            pub_date = news.get("pub_date")
            if isinstance(pub_date, datetime) and pub_date < event_time:
                matched_news.append({
                    "title": news["title"],
                    "pub_date": pub_date.strftime("%Y-%m-%d %H:%M"),
                    "link": news.get("link", "")
                })

        if not matched_news and len(news_list) > 0:
            for news in news_list[:3]:
                pub_date = news.get("pub_date")
                matched_news.append({
                    "title": news["title"],
                    "pub_date": pub_date.strftime("%Y-%m-%d %H:%M") if isinstance(pub_date, datetime) else "",
                    "link": news.get("link", "")
                })

        matched_results[event_time.strftime("%Y-%m-%d %H:%M")] = matched_news

    return matched_results
