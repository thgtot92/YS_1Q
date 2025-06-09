from naver_finance_crawler import fetch_intraday_price
from investor_crawler import fetch_investor_trend
from slack_sender import send_to_slack
from llm_reporter import get_llm_report
import pandas as pd
from news_api_caller import NaverNewsSearcher, search_news_advanced
from datetime import datetime
import pytz

def detect_price_events_by_day(df: pd.DataFrame, threshold: float = 0.01):
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    start_price = df.iloc[0]["price"]
    df["pct_from_start"] = (df["price"] - start_price) / start_price
    event_rows = df[df["pct_from_start"].abs() >= threshold].copy()
    event_rows["event_type"] = event_rows["pct_from_start"].apply(
        lambda x: "상승" if x > 0 else "하락"
    )
    return event_rows[["datetime", "price", "pct_from_start", "event_type"]].reset_index(drop=True)


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

def build_prompt(input_data):
    header = f"{input_data['date']}일 {input_data['stock']} 종목에 대한 요약 리포트를 생성해주세요.\n"

    ts_section = "📈 시계열 요약:\n"
    for t in input_data["timeseries_summary"]:
        time_str = str(t.get('datetime', '시간없음'))[-8:]
        ts_section += f"- {time_str} (가격: {t.get('price', '?')}원, 거래량: {t.get('volume', '?')})\n"

    news_section = "\n📰 관련 뉴스 요약:\n"
    if input_data["news_summary"]:
        for n in input_data["news_summary"]:
            news_section += f"- {n['pub_date']} | [unknown] {n['title']}\n"
    else:
        news_section += "- 관련 뉴스가 없습니다.\n"

    investor = input_data["investor_summary"]
    investor_section = "\n📊 투자자 수급 요약:\n"
    investor_section += f"- 기관 순매수: {investor['기관']}주\n"
    investor_section += f"- 외국인 순매수: {investor['외국인']}주\n"

    task = "\n이 정보를 바탕으로 하루 동안의 주요 흐름, 투자자 수급, 뉴스 영향 등을 종합적으로 분석한 자연어 보고서를 작성해주세요."

    return header + ts_section + news_section + investor_section + task

def build_event_prompt(event_time, event_type, price_before, price_now, matched_news):
    """
    단일 이벤트에 대한 인과 분석용 프롬프트 생성
    """
    direction = "상승" if event_type == "상승" else "하락"
    pct_change = ((price_now - price_before) / price_before) * 100

    header = f"{event_time} 삼성전자 주가가 {direction}했습니다.\n"
    header += f"가격 변화: {price_before}원 → {price_now}원 ({pct_change:.2f}%)\n"
    header += "이 시점 이전에 다음과 같은 뉴스들이 있었습니다:\n"

    news_section = ""
    for i, news in enumerate(matched_news, 1):
        news_section += f"{i}. {news['pub_date']} - {news['title']}\n"

    instruction = "\n이러한 뉴스들이 주가 변화에 어떤 영향을 미쳤는지 분석해주세요. 주요 원인으로 작용한 뉴스가 무엇인지도 판단해주세요."

    return header + news_section + instruction

def build_event_prompt(event_row, related_news, stock_name):
    time = event_row["datetime"]
    price = event_row["price"]
    direction = event_row["event_type"]

    news_section = "\n".join(
        [f"- {n['pub_date']} | {n['title']}" for n in related_news]
    ) if related_news else "- 관련 뉴스 없음"

    prompt = f"""다음은 {stock_name} 주식의 {direction} 이벤트에 대한 분석 요청입니다.

🕒 이벤트 시각: {time}
📈 주가: {price}원

📑 이벤트 발생 전 뉴스:
{news_section}

이 이벤트가 어떤 이유로 발생했는지 뉴스 내용을 바탕으로 분석해 주세요. 근거를 명확히 밝혀 주시고, 뉴스가 직접적인 영향을 미쳤는지에 대한 판단도 포함해 주세요.
"""
    return prompt

def main():
    stock_code = '005930'
    stock_name = '삼성전자'
    date = '2025-06-04'
    client_id = "JEuS9xkuWGpP40lsI9Kz"
    client_secret = "I6nujCm0xF"

    try:
        df = fetch_intraday_price(stock_code, date)
        df = df.sort_values("datetime").reset_index(drop=True)

        events = detect_price_events_by_day(df, threshold=0.005)
        print("📊 이벤트 감지 결과:\n", events)

        start = df.iloc[0]
        middle = df.iloc[len(df)//2]
        end = df.iloc[-1]
        timeseries_summary = [start.to_dict(), middle.to_dict(), end.to_dict()]

        searcher = NaverNewsSearcher(client_id, client_secret)
        raw_news_items = search_news_advanced(searcher, stock_name, date)
        formatted_news = searcher.format_news_data(raw_news_items)

        matched_news = match_news_before_events(formatted_news, events)

        print("\n📑 각 이벤트별 관련 뉴스:")
        for event_time, news_list in matched_news.items():
            print(f"\n🕒 이벤트 시간: {event_time}")
            for n in news_list[:3]:
                print(f" - {n['pub_date']} | {n['title']}")

        # 가장 마지막 이벤트 기준으로 뉴스 사용
        latest_event_time = max(matched_news.keys()) if matched_news else None
        selected_news = matched_news.get(latest_event_time, [])[:5] if latest_event_time else []

        news_summary = [
            {
                'title': n['title'],
                'pub_date': n['pub_date'],
                'sentiment': 'unknown'
            }
            for n in selected_news
        ]

        investor_info = fetch_investor_trend(stock_code, date)

        llm_input = {
            'stock': stock_name,
            'date': date,
            'timeseries_summary': timeseries_summary,
            'news_summary': news_summary,
            'investor_summary': investor_info
        }

        prompt = build_prompt(llm_input)
        print("==== 생성된 Prompt ====")
        print(prompt)

        report = get_llm_report(prompt)
        print("\n📄 생성된 리포트:\n", report)

        slack_url = "https://hooks.slack.com/services/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"
        success = send_to_slack(report, slack_url)
        print("✅ Slack 전송 완료" if success else "❌ Slack 전송 실패")

    except Exception as e:
        print("🚨 오류 발생:", e)


if __name__ == "__main__":
    main()
