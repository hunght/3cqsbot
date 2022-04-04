from cProfile import run
import configparser
import argparse
from distutils.log import debug
import re
import logging
import asyncio
import sys
import os
import portalocker
import math

from telethon import TelegramClient, events
from py3cw.request import Py3CW
from singlebot import SingleBot
from multibot import MultiBot
from signals import Signals
from logging.handlers import RotatingFileHandler


######################################################
#                       Config                       #
######################################################
config = configparser.ConfigParser()
config.read("config.ini")

parser = argparse.ArgumentParser(
    description="3CQSBot bringing 3CQS signals to 3Commas."
)
parser.add_argument(
    "-l",
    "--loglevel",
    metavar="loglevel",
    type=str,
    nargs="?",
    default="info",
    help="loglevel during runtime - use info, debug, warning, ...",
)

args = parser.parse_args()

######################################################
#                        Init                        #
######################################################

 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config["general"]["file_handler"]),
        logging.StreamHandler()
    ]
)

p3cw = Py3CW(
    key=config["commas"]["key"],
    secret=config["commas"]["secret"],
    request_options={
        "request_timeout": config["commas"].getint("timeout"),
        "nr_of_retries": config["commas"].getint("retries"),
        "retry_backoff_factor": config["commas"].getfloat("delay_between_retries"),
    },
)

# Initialize Telegram API client
client = TelegramClient(
    config["telegram"]["sessionfile"],
    config["telegram"]["api_id"],
    config["telegram"]["api_hash"],
)

# Set logging facility
if config["general"].getboolean("debug"):
    loglevel = "DEBUG"
else:
    loglevel = getattr(logging, args.loglevel.upper(), None)

# Set logging output
handler = logging.StreamHandler()

if config["general"].getboolean("log_to_file"):
    handler = logging.handlers.RotatingFileHandler(
        config["general"]["log_file_path"],
        maxBytes=config["general"].getint("log_file_size"),
        backupCount=config["general"].getint("log_file_count"),
    )

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=loglevel,
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[handler],
)

# Initialize variables
asyncState = type("", (), {})()
asyncState.btcbool = True
asyncState.botswitch = True
asyncState.chatid = ""
asyncState.fh = 0

######################################################
#                     Methods                        #
######################################################
def run_once():
    asyncState.fh = open(os.path.realpath(__file__), "r")
    try:
        portalocker.lock(asyncState.fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except:
        sys.exit(
            "Another 3CQSBot is already running in this directory - please use another one!"
        )


# Check for single instance run
run_once()


def parse_tg(raw_text):
    return raw_text.split("\n")


def tg_data(text_lines):
    # Make sure the message is a signal
    # 6 Lines old Telegram signal - will be removed after @Mantis update
    if len(text_lines) == 6:
        data = {}
        signal = "old"
        token = text_lines[1].replace("#", "")
        action = text_lines[2].replace("BOT_", "")
        volatility_score = text_lines[3].replace("Volatility Score ", "")

        if volatility_score == "N/A":
            volatility_score = 9999999

        priceaction_score = text_lines[4].replace("Price Action Score ", "")

        if priceaction_score == "N/A":
            priceaction_score = 9999999

        symrank = text_lines[5].replace("SymRank #", "")

        if symrank == "N/A":
            symrank = 9999999

        data = {
            "signal": signal,
            "pair": config["trading"]["market"] + "_" + token,
            "action": action,
            "volatility": float(volatility_score),
            "price_action": float(priceaction_score),
            "symrank": int(symrank),
        }
    # 7 Lines new Telegram signal
    elif len(text_lines) == 7:
        data = {}
        signal = text_lines[1]
        token = text_lines[2].replace("#", "")
        action = text_lines[3].replace("BOT_", "")
        volatility_score = text_lines[4].replace("Volatility Score ", "")

        if volatility_score == "N/A":
            volatility_score = 9999999

        priceaction_score = text_lines[5].replace("Price Action Score ", "")

        if priceaction_score == "N/A":
            priceaction_score = 9999999

        symrank = text_lines[6].replace("SymRank #", "")

        if symrank == "N/A":
            symrank = 9999999

        data = {
            "signal": signal,
            "pair": config["trading"]["market"] + "_" + token,
            "action": action,
            "volatility": float(volatility_score),
            "price_action": float(priceaction_score),
            "symrank": int(symrank),
        }
    # Symrank list
    elif len(text_lines) == 17:
        pairs = {}
        data = []

        if "Volatile" not in text_lines[0]:
            for row in text_lines:
                if ". " in row:
                    # Sort the pair list from Telegram
                    line = re.split(" +", row)
                    pairs.update(
                        {int(line[0][:-1]): line[1], int(line[2][:-1]): line[3]}
                    )

            allpairs = dict(sorted(pairs.items()))
            data = list(allpairs.values())

    else:
        data = False

    return data


def bot_data():
    # Gets information about existing bot in 3Commas
    botlimit = 200
    pages = math.ceil(botlimit / 100)
    bots = []

    for page in range(1, pages + 1):
        if page == 1:
            offset = 0
        else:
            offset = (page - 1) * 100

        error, data = p3cw.request(
            entity="bots",
            action="",
            additional_headers={"Forced-Mode": config["trading"]["trade_mode"]},
            payload={"limit": 100, "offset": offset},
        )

        if error:
            sys.exit(error["msg"])
        else:
            if data:
                bots += data
            else:
                break

    return bots


def account_data():
    # Gets information about the used 3commas account (paper or real)
    account = {}

    error, data = p3cw.request(
        entity="accounts",
        action="",
        additional_headers={"Forced-Mode": config["trading"]["trade_mode"]},
    )

    if error:
        logging.debug(error["msg"])
        sys.tracebacklimit = 0
        sys.exit("Problem fetching account data from 3commas api - stopping!")
    else:
        for accounts in data:
            if accounts["name"] == config["trading"]["account_name"]:
                account.update({"id": str(accounts["id"])})
                account.update({"market_code": str(accounts["market_code"])})

        if "id" not in account:
            sys.tracebacklimit = 0
            sys.exit(
                "Account with name " + config["trading"]["account_name"] + " not found"
            )

    return account


def pair_data(account):
    pairs = []

    error, data = p3cw.request(
        entity="accounts",
        action="market_pairs",
        additional_headers={"Forced-Mode": config["trading"]["trade_mode"]},
        payload={"market_code": account["market_code"]},
    )

    if error:
        logging.debug(error["msg"])
        sys.tracebacklimit = 0
        sys.exit("Problem fetching pair data from 3commas api - stopping!")
    else:
        for pair in data:
            if config["trading"]["market"] in pair:
                if pair not in config["filter"]["token_denylist"]:
                    pairs.append(pair)

    return pairs


async def symrank():
    logging.info(
        "Sending /symrank command to 3C Quick Stats on Telegram to get new pairs"
    )
    await client.send_message(asyncState.chatid, "/symrank")


async def botswitch():
    while True:
        if not asyncState.btcbool and not asyncState.botswitch:
            logging.info("Enabling Bot because of BTC uptrend")
            asyncState.botswitch = True
            logging.debug("Botswitch: " + str(asyncState.botswitch))
            if config["dcabot"].getboolean("single"):
                logging.info("Not activating old single bots (waiting for new signals.")
            else:
                # Send new top 30 for activating the multibot
                await symrank()

        elif asyncState.btcbool and asyncState.botswitch:
            logging.info("Disabling Bot because of BTC downtrend")
            asyncState.botswitch = False
            logging.debug("Botswitch: " + str(asyncState.botswitch))
            if config["dcabot"].getboolean("single"):
                bot = SingleBot([], bot_data(), {}, config, p3cw, logging)
                bot.disable(bot_data(), True)
            else:
                bot = MultiBot([], bot_data(), {}, 0, config, p3cw, logging)
                bot.disable()

        else:
            logging.debug("Nothing do to")
            logging.debug("Botswitch: " + str(asyncState.botswitch))

        await asyncio.sleep(60)


def _handle_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task cancellation should not be logged as an error.
    except Exception:  # pylint: disable=broad-except
        logging.exception("Exception raised by task = %r", task)


@client.on(events.NewMessage(chats=config["telegram"]["chatroom"]))
async def my_event_handler(event):

    if (
        asyncState.btcbool
        and config["filter"].getboolean("btc_pulse")
        and not config["filter"].getboolean("ext_botswitch")
    ):
        logging.info(
            "New 3CQS signal not processed - Bot stopped because of BTC downtrend"
        )
    else:

        logging.info("New 3CQS signal incoming...")

        tg_output = tg_data(parse_tg(event.raw_text))
        logging.debug("TG msg: " + str(tg_output))
        bot_output = bot_data()
        account_output = account_data()
        pair_output = pair_data(account_output)

        if tg_output and not isinstance(tg_output, list):

            # Check if it is the right signal
            if tg_output["signal"] == config["filter"]["symrank_signal"]:

                # Choose multibot or singlebot
                if config["dcabot"].getboolean("single"):
                    bot = SingleBot(
                        tg_output, bot_output, account_output, config, p3cw, logging
                    )
                else:
                    bot = MultiBot(
                        tg_output,
                        bot_output,
                        account_output,
                        pair_output,
                        config,
                        p3cw,
                        logging,
                    )
                    # Every signal triggers a new multibot deal
                    bot.trigger(triggeronly=True)

                # Trigger bot if limits passed
                if tg_output["volatility"] != 0 and tg_output["pair"] in pair_output:
                    if (
                        tg_output["volatility"]
                        >= config["filter"].getfloat("volatility_limit_min")
                        and tg_output["volatility"]
                        <= config["filter"].getfloat("volatility_limit_max")
                        and tg_output["price_action"]
                        >= config["filter"].getfloat("price_action_limit_min")
                        and tg_output["price_action"]
                        <= config["filter"].getfloat("price_action_limit_max")
                        and tg_output["symrank"]
                        >= config["filter"].getint("symrank_limit_min")
                        and tg_output["symrank"]
                        <= config["filter"].getint("symrank_limit_max")
                    ) or tg_output["action"] == "STOP":

                        bot.trigger()

                    else:
                        logging.info("Trading limits reached. Deal not placed.")
                else:
                    logging.info(
                        "Pair "
                        + tg_output["pair"]
                        + " is not traded on account "
                        + config["trading"]["account_name"]
                    )
            else:
                logging.info("Signal not configured, doing nothing.")

        elif tg_output and isinstance(tg_output, list):
            if not config["dcabot"].getboolean("single"):
                # Create or update multibot with pairs from "/symrank"
                bot = MultiBot(
                    tg_output,
                    bot_output,
                    account_output,
                    pair_output,
                    config,
                    p3cw,
                    logging,
                )
                bot.create()
            else:
                logging.debug(
                    "Ignoring /symrank call, because we're running in single mode!"
                )


async def main():
    signals = Signals(logging)

    logging.debug("Refreshing cache...")

    user = await client.get_participants("The3CQSBot")
    asyncState.chatid = user[0].id

    logging.info("*** 3CQS Bot started ***")

    if not config["dcabot"].getboolean("single"):
        await symrank()

    if config["filter"].getboolean("btc_pulse") and not config["filter"].getboolean(
        "ext_botswitch"
    ):
        btcbooltask = client.loop.create_task(signals.getbtcbool(asyncState))
        btcbooltask.add_done_callback(_handle_task_result)
        switchtask = client.loop.create_task(botswitch())
        switchtask.add_done_callback(_handle_task_result)

        while True:
            await btcbooltask
            await switchtask


with client:
    client.loop.run_until_complete(main())

client.start()

if not config["filter"].getboolean("btc_pulse"):
    client.run_until_disconnected()
