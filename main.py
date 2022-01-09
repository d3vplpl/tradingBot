import secret
import os,time
import xml.etree.ElementTree as ET
import requests
from datetime import date, datetime, timedelta
import csv
import numpy as np
import nltk
#nltk.download('popular')
nltk.download('vader_lexicon')
from nltk.sentiment import SentimentIntensityAnalyzer
from bs4 import BeautifulSoup
import feedparser

#binance API
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceOrderException
from binance import BinanceSocketManager
from binance import ThreadedWebsocketManager
from twisted.internet import reactor

from itertools import count

#google translate
from googletrans import Translator, constants
from pprint import pprint

client = Client(secret.test_API_key, secret.test_secret)
client.API_URL = 'https://testnet.binance.vision/api'



############################################
#     USER INPUT VARIABLES LIVE BELOW      #
# You may edit those to configure your bot #
############################################


# select what coins to look for as keywords in articles headlines
# The key of each dict MUST be the symbol used for that coin on Binance
# Use each list to define keywords separated by commas: 'XRP': ['ripple', 'xrp']
# keywords are case sensitive
keywords = {
    'XRP': ['ripple', 'xrp', 'XRP', 'Ripple', 'RIPPLE'],
    'BTC': ['BTC', 'bitcoin', 'Bitcoin', 'BITCOIN'],
    'XLM': ['Stellar Lumens', 'XLM'],
    'BCH': ['Bitcoin Cash', 'BCH'],
    'ETH': ['ETH', 'Ethereum'],
    'BNB': ['BNB', 'Binance Coin'],
    'LTC': ['LTC', 'Litecoin'],
    'DOT': ['DOT', 'DOT', 'Polkadot', 'Polka', 'POLKADOT'],
    'CINU': ['CINU', 'Cheems Inu', 'CHEEMS INU', 'Cheems']
    }

# The Buy amount in the PAIRING symbol, by default USDT
# 100 will for example buy the equivalent of 100 USDT in Bitcoin.
QUANTITY = 100

# define what to pair each coin to
# AVOID PAIRING WITH ONE OF THE COINS USED IN KEYWORDS
PAIRING = 'USDT'

# define how positive the news should be in order to place a trade
# the number is a compound of neg, neu and pos values from the nltk analysis
# input a number between -1 and 1
SENTIMENT_THRESHOLD = 0.5

# define the minimum number of articles that need to be analysed in order
# for the sentiment analysis to qualify for a trade signal
# avoid using 1 as that's not representative of the overall sentiment
MINUMUM_ARTICLES = 10

# define how often to run the code (check for new + try to place trades)
# in minutes
REPEAT_EVERY = 30

# current price of CRYPTO pulled through the websocket
CURRENT_PRICE = {}

feeds = []



def get_headlines():

    headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:87.0) Gecko/20100101 Firefox/87.0'}

    headlines = {'source': [], 'title': [], 'pubDate': []}
    translator = Translator()
    for feed in feeds:
        try:

            # grab XML for each RSS feed
            r = requests.get(feed, headers=headers, timeout=7)
            root = ET.fromstring(r.text)
            channel = root.find('channel/item/title').text
            translation = translator.translate(channel)
            str_channel = str(translation.text)
            pubDate = root.find('channel/item/pubDate').text

            headlines['source'].append(feed)
            headlines['pubDate'].append(pubDate)
            headlines['title'].append(str_channel.encode('UTF-8').decode('UTF-8'))
            print(channel)

        except Exception as err :
            print(f'Could not parse {feed}')
            print(err)
    print(headlines)
    return headlines

def categorise_headlines():
    headlines = get_headlines()
    categorised_headlines = {}

    for keyword in keywords:
        categorised_headlines['{0}'.format(keyword)] = []

    for keyword in keywords:
        for headline in headlines['title']:
            if any (key in headline for key in keywords[keyword]):
                categorised_headlines[keyword].append(headline)

    print('Categorised headlines: ', categorised_headlines)
    return categorised_headlines

def analyse_headlines():
    '''Analyse categorised headlines and return NLP scores'''
    sia = SentimentIntensityAnalyzer()
    categorised_headlines = categorise_headlines()
    sentiment = {}

    for coin in categorised_headlines:
        if len(categorised_headlines[coin]) > 0:
            #create dict for each coin
            sentiment['{0}'.format(coin)] = []
            #append sentiment to dict
            for title in categorised_headlines[coin]:
                sentiment[coin].append(sia.polarity_scores(title))
    print(sentiment)
    return sentiment

def compile_sentiment():
    '''Arranges every compound value into a list of each coin'''
    sentiment = analyse_headlines()
    compiled_sentiment = {}

    for coin in sentiment:
        compiled_sentiment[coin] = []

        for item in sentiment[coin]:
            compiled_sentiment[coin].append(sentiment[coin][sentiment[coin].index(item)]['compound'])

    return compiled_sentiment

def calculate_compound_average():
    '''Calculates and returns the average compound sentiment for each coin'''
    compiled_sentiment = compile_sentiment()
    headlines_analysed = {}

    for coin in compiled_sentiment:
        headlines_analysed[coin] = len(compiled_sentiment[coin])

        #calculate the average using numpy if there is more than 1 element in list
        compiled_sentiment[coin] = np.array(compiled_sentiment[coin])
        #get the mean
        compiled_sentiment[coin] = np.mean(compiled_sentiment[coin])
        #convert to scalar
        compiled_sentiment[coin] = compiled_sentiment[coin].item()

    return compiled_sentiment, headlines_analysed


def buy():
    '''check if sentiment is positive an keyword is found for each handle '''
    compiled_sentiment, headlines_analysed = calculate_compound_average()
    volume = calculate_volume()

    for coin in compiled_sentiment:

        if compiled_sentiment[coin] > SENTIMENT_THRESHOLD and headlines_analysed[coin] > MINUMUM_ARTICLES:
            print('preparing to buy {coin} with {volume} USDT at {CURRENT_PRICE[coin+PAIRING]}')
            #create a test order before pushing actual order
            test_order = client.create_test_order(
                symbol=coin+PAIRING,
                side='BUY',
                type='MARKET',
                quantity=volume[coin+PAIRING]
            )
            try:
                buy_limit = client.create_order(
                    symbol=coin+PAIRING,
                    side='BUY',
                    type='MARKET',
                    quantiy=volume[coin+PAIRING]
                )

            except BinanceAPIException as e:
                print(e)
            except BinanceOrderException as e:
                print(e)

            #no exception
            else:
                order = client.get_all_orders(symbol=coin+PAIRING, limit=1)
                time = order[0]['time'] / 1000
                utc_time = datetime.fromtimestamp(time)
                bought_at = CURRENT_PRICE[coin+PAIRING]

                print(f"order {order[0]['orderId']} has been placed on {coin} with {order[0]['origQtyf']} at {utc_time} and boutght at {bought_at}")

                return bought_at, order
        else:
            print(f'Sentiment not positive enough for {coin}, or not enough headlines analysed: {compiled_sentiment[coin]}, {headlines_analysed[coin]}')



def open_csv_file():

    with open ('Crypto feeds.csv') as csv_file:

        csv_reader = csv.reader(csv_file)
        next(csv_reader) #remove header

        for row in csv_reader:
            feeds.append(row[0])

def calculate_volume():
    '''Calculate volume of crypto in USDT'''

    while CURRENT_PRICE == {}:
        print('Connecting to socket...')
        time.sleep(3)
    else:
        volume = {}
        for coin in CURRENT_PRICE:
            volume[coin] = float(QUANTITY / float(CURRENT_PRICE[coin]))
            volume[coin] = float('{:.6f}'.format(volume[coin]))
        return volume

def ticker_socket(msg):
    if msg['e'] != 'error':
        global CURRENT_PRICE
        #print('callback msg ', msg['s'], msg['c'])
        CURRENT_PRICE['{0}'.format(msg['s'])] = msg['c']
        #CURRENT_PRICE[(msg['s'])] = msg['c']
    else:
        print('error!')

testing = False
if testing:
    #this is just to test nltk
    test_sia = SentimentIntensityAnalyzer()
    translator = Translator()
    #translation = translator.translate("Hola Mundo")
    translation = translator.translate('Bitcoin to złoto millenialsów')
    print(translation.text)
    print(test_sia.polarity_scores('Bitcoin is better than gold'))
    quit()


twm = ThreadedWebsocketManager(api_key=secret.test_API_key, api_secret=secret.test_secret)

twm.start()
for coin in keywords:

    print(coin+PAIRING)
    conn_key = twm.start_symbol_ticker_socket(symbol=coin+PAIRING, callback=ticker_socket)

open_csv_file()

for i in count():
    buy()
    print(f'Iteration {i}')
    time.sleep(60 * REPEAT_EVERY)

twm.join()
twm.stop()




