#    client_id = "JEuS9xkuWGpP40lsI9Kz"
#    client_secret = "I6nujCm0xF"
#    slack_url = "https://hooks.slack.com/services/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"
from naver_finance_crawler import fetch_intraday_price
from investor_crawler import fetch_investor_trend
from slack_sender import send_to_slack, send_event_summaries_to_slack
from llm_reporter import get_llm_report, analyze_events_with_llm
from news_api_caller import NaverNewsSearcher, search_news_advanced, format_news_data, match_news_before_events
import pandas as pd
import os


def detect_price_events_by_day(df, threshold=0.01):
    df = df.copy()
    df = df.sort_values("datetime").reset_index(drop=True)
    start_price = df.iloc[0]['price']
    df['pct_from_start'] = (df['price'] - start_price) / start_price
    df['event_type'] = df['pct_from_start'].apply(lambda x: "상승" if x >= threshold else ("하락" if x <= -threshold else None))
    return df[df['event_type'].notnull()][['datetime', 'price', 'pct_from_start', 'event_type']]


def main():
    stock_code = '005930'  # 삼성전자
    stock_name = '삼성전자'
    date = '2025-06-09'
    client_id = os.getenv("NAVER_CLIENT_ID") or "JEuS9xkuWGpP40lsI9Kz"
    client_secret = os.getenv("NAVER_CLIENT_SECRET") or "I6nujCm0xF"
    slack_url = os.getenv("SLACK_WEBHOOK_URL") or "https://hooks.slack.com/services/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"

    try:
        # 주가 데이터 및 이벤트 감지
        df = fetch_intraday_price(stock_code, date)
        events = detect_price_events_by_day(df)
        print("\n📊 이벤트 감지 결과:\n", events)

        # 뉴스 검색 및 처리
        searcher = NaverNewsSearcher(client_id, client_secret)
        
        # 1. 뉴스 검색 (이미 해당 날짜로 필터링됨)
        raw_news_items = search_news_advanced(searcher, stock_name, date)
        print(f"\n📰 검색된 뉴스 개수: {len(raw_news_items)}")
        
        # 2. 뉴스 포맷팅
        formatted_news = format_news_data(raw_news_items)
        print(f"📰 포맷팅된 뉴스 개수: {len(formatted_news)}")
        
        # 디버깅: 뉴스 출력
        if formatted_news:
            print("\n📑 검색된 뉴스 목록:")
            for i, news in enumerate(formatted_news[:5], 1):
                print(f"{i}. {news['pub_date']} - {news['title'][:50]}...")
        else:
            print("❌ 검색된 뉴스가 없습니다.")

        # 3. 이벤트와 뉴스 매칭
        matched_news_dict = match_news_before_events(formatted_news, events)
        
        # 디버깅: 매칭 결과 출력
        print("\n🔗 이벤트별 매칭된 뉴스:")
        for event_time, news_list in matched_news_dict.items():
            print(f"📅 {event_time}: {len(news_list)}개 뉴스")
            for news in news_list[:3]:
                print(f"  - {news['title'][:50]}...")

        # 4. LLM 이벤트 분석
        event_summaries = analyze_events_with_llm(events, matched_news_dict, stock_name)
        send_event_summaries_to_slack(event_summaries, slack_url)

        # 5. 전체 리포트 생성을 위한 데이터 준비
        first = df.iloc[0]
        middle = df.iloc[len(df)//2]
        last = df.iloc[-1]
        timeseries_summary = [first.to_dict(), middle.to_dict(), last.to_dict()]
        investor_info = fetch_investor_trend(stock_code, date)

        # 6. 뉴스 요약 생성 (중복 제거)
        news_summary = []
        seen_titles = set()
        
        for event_time, news_list in matched_news_dict.items():
            for news in news_list:
                if news["title"] not in seen_titles:
                    seen_titles.add(news["title"])
                    news_summary.append({
                        "time": news["pub_date"],
                        "title": news["title"],
                        "sentiment": "unknown"
                    })
        
        # 매칭된 뉴스가 없는 경우 전체 뉴스에서 일부 사용
        if not news_summary and formatted_news:
            for news in formatted_news[:5]:
                news_summary.append({
                    "time": news["pub_date"].strftime("%Y-%m-%d %H:%M") if news.get("pub_date") else "시간없음",
                    "title": news["title"],
                    "sentiment": "unknown"
                })

        print(f"\n📰 최종 뉴스 요약 개수: {len(news_summary)}")

        # 7. LLM 입력 데이터 구성
        llm_input = {
            'stock': stock_name,
            'date': date,
            'timeseries_summary': timeseries_summary,
            'news_summary': news_summary,
            'investor_summary': investor_info
        }

        def build_prompt(input_data):
            header = f"{input_data['date']}일 {input_data['stock']} 종목에 대한 요약 리포트를 생성해주세요.\n"
            ts_section = "\n📈 시계열 요약:\n"
            for t in input_data["timeseries_summary"]:
                ts_time = str(t['datetime'])[-8:] if isinstance(t['datetime'], str) else t['datetime'].strftime('%H:%M:%S')
                ts_section += f"- {ts_time} (가격: {t['price']}원, 거래량: {t['volume']})\n"

            news_section = "\n📰 관련 뉴스 요약:\n"
            if input_data["news_summary"]:
                for n in input_data["news_summary"][:10]:
                    news_section += f"- {n['time']} | [{n['sentiment']}] {n['title']}\n"
            else:
                news_section += "- 관련 뉴스가 없습니다.\n"

            investor = input_data["investor_summary"]
            investor_section = f"\n\n📊 투자자 수급 요약:\n- 기관 순매수: {investor['기관']}주\n- 외국인 순매수: {investor['외국인']}주"

            task = "\n\n이 정보를 바탕으로 하루 동안의 주요 흐름을 요약한 자연어 리포트를 작성해주세요."
            return header + ts_section + news_section + investor_section + task

        prompt = build_prompt(llm_input)
        print("\n==== 생성된 Prompt ====\n")
        print(prompt)

        report = get_llm_report(prompt)
        print("\n📄 생성된 종합 리포트:\n", report)
        send_to_slack(report, slack_url)

    except Exception as e:
        print("🚨 오류 발생:", e)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()