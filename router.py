import json
import logging

from telegram import Update, Bot, ChatAction

from dialog import Dialog
from nlu import *
from policy import GraphBasedSberdemoPolicy
from say_actions import Sayer

from telegram.ext import Updater
from telegram.ext import CommandHandler, MessageHandler, Filters

import threading

from slots import read_slots_serialized, read_slots_from_tsv
from tomita.name_parser import NameParser
# from train_joint_classifier import joint_intent_and_slot_classifier
from train_svm import BASE_CLF_INTENT

from concurrent.futures import ThreadPoolExecutor

import argparse


def format_route(route):
    for i in range(len(route)):
        if isinstance(route[i], list):
            format_route(route[i])
        elif isinstance(route[i], str):
            route[i] = {"slot": route[i], "condition": "any"}
        elif isinstance(route[i], dict):
            if "action" in route[i]:
                if "relevant_slots" in route[i]:
                    route[i]["relevant_slots"] = {slot: None for slot in route[i]["relevant_slots"]}
            elif len(route[i]) == 1:
                for key, val in route[i].items():
                    route[i] = {"slot": val, "condition": key}


def parse_route(file_name):
    with open(file_name, 'r') as f:
        data = json.load(f)
    for intent, route in data.items():
        format_route(route)

    return data


def set_logger(level=logging.DEBUG):
    logger = logging.getLogger('router')
    logger.setLevel(level)

    fh = logging.FileHandler(os.path.join('.', 'logs', 'router.log'))
    fh.setLevel(level)

    ch = logging.StreamHandler()
    ch.setLevel(level)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)


def get_logger():
    return logging.getLogger('router')


def main(args=None):
    parser = argparse.ArgumentParser(description='Run the bot')

    parser.add_argument('--debug', dest='debug', action='store_true', default=False,
                        help="send debug messages to the user")

    debug = vars(parser.parse_args(args))['debug']

    set_logger()
    get_logger().info('Starting...')

    fname = 'routes.json'
    data = parse_route(fname)

    pipe = create_pipe()

    models_path = './models_nlu'

    # use joint model for every slot
    # slots = read_slots_from_tsv(pipe)
    # slots = joint_intent_and_slot_classifier(slots, models_path)

    # use single model for each slot
    slots = read_slots_serialized(models_path, pipe)

    name_parser = NameParser()

    sayer = Sayer(slots, pipe)

    executor = ThreadPoolExecutor()

    humans = {}

    def new_dialog(user):
        return Dialog(pipe, StatisticalNLUModel(slots, SentenceClassifier(BASE_CLF_INTENT, model_path=os.path.join(models_path, "IntentClassifier.model"), model_name="IntentClassifier.model"), name_parser),
                      GraphBasedSberdemoPolicy(data, slots, sayer), user, debug=debug, patience=2)

    def start(bot: Bot, update: Update):
        chat_id = update.message.chat_id
        try:
            humans[chat_id] = new_dialog(update.effective_user)
        except Exception as e:
            get_logger().error(e)
        bot.send_message(chat_id=chat_id, text=sayer.say('greeting', {}))

    def send_delayed(bot: Bot, chat_id, messages: list, interval=0.7):
        m = messages.pop(0)
        try:
            bot.send_message(chat_id=chat_id, text=m, parse_mode='HTML')
        except Exception as e:
            get_logger().error(e)
            bot.send_message(chat_id=chat_id, text='bot.send ERROR: ' + str(e))
        if messages:
            threading.Timer(interval, send_delayed, [bot, chat_id, messages, interval]).start()

    def user_client(bot: Bot, update):

        chat_id = update.message.chat_id
        if chat_id not in humans:
            humans[chat_id] = new_dialog(update.effective_user)
        user_msg = update.message.text or '__geo__ ' + str(update.message.location)
        dialog = humans[chat_id]

        threading.Timer(0.5, bot.send_chat_action, [chat_id, ChatAction.TYPING]).start()

        dialog.promise = dialog.promise\
            .then(lambda _: executor.submit(dialog.generate_response, user_msg))\
            .then(lambda bot_responses: send_delayed(bot, chat_id, bot_responses, 0.7))

    updater = Updater(token=os.environ['SBER_DEMO_BOT_TOKEN'])
    dispatcher = updater.dispatcher
    start_handler = CommandHandler('start', start)
    msg_handler = MessageHandler(Filters.text | Filters.location, user_client)

    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(msg_handler)

    updater.start_polling()

    get_logger().info('Ready')

    updater.idle()


if __name__ == '__main__':
    main()
