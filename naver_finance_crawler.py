import requests
from bs4 import BeautifulSoup
import pandas as pd

def fetch_intraday_price(stock_code: str, date: str):
    df_all = []
    for page in range(1, 41):  # 최대 40페이지 (09:00 ~ 15:30)
        url = f"https://finance.naver.com/item/sise_time.naver?code={stock_code}&thistime={date.replace('-', '')}153000&page={page}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.select_one("table.type2")

        if not table:
            continue

        rows = table.find_all('tr')
        data = []
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6: continue
            try:
                time = cols[0].text.strip()
                price = int(cols[1].text.strip().replace(',', ''))
                volume = int(cols[5].text.strip().replace(',', ''))
                data.append([time, price, volume])
            except:
                continue
        if data:
            df = pd.DataFrame(data, columns=['time', 'price', 'volume'])
            df_all.append(df)

    if not df_all:
        raise ValueError("시계열 데이터를 수집하지 못했습니다.")

    result = pd.concat(df_all)
    result['datetime'] = pd.to_datetime(date + ' ' + result['time'])
    return result[['datetime', 'price', 'volume']]
