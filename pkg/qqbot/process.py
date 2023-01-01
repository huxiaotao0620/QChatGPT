# 此模块提供了消息处理的具体逻辑的接口
import datetime

import pkg.qqbot.manager as manager
from func_timeout import func_set_timeout
import logging
import openai

from mirai import Image, MessageChain
from mirai.models.message import Quote

import config

import pkg.openai.session
import pkg.openai.manager

processing = []


@func_set_timeout(config.process_message_timeout)
def process_message(launcher_type: str, launcher_id: int, text_message: str, message_chain: MessageChain,
                    sender_id: int) -> MessageChain:
    global processing

    mgr = pkg.qqbot.manager.get_inst()

    reply = []
    session_name = "{}_{}".format(launcher_type, launcher_id)

    pkg.openai.session.get_session(session_name).acquire_response_lock()

    try:
        if session_name in processing:
            pkg.openai.session.get_session(session_name).release_response_lock()
            return ["[bot]err:正在处理中，请稍后再试"]

        processing.append(session_name)

        try:

            if text_message.startswith('!') or text_message.startswith("！"):  # 指令
                try:
                    logging.info(
                        "[{}]发起指令:{}".format(session_name, text_message[:min(20, len(text_message))] + (
                            "..." if len(text_message) > 20 else "")))

                    cmd = text_message[1:].strip().split(' ')[0]

                    params = text_message[1:].strip().split(' ')[1:]
                    if cmd == 'help':
                        reply = ["[bot]" + config.help_message]
                    elif cmd == 'reset':
                        pkg.openai.session.get_session(session_name).reset(explicit=True)
                        reply = ["[bot]会话已重置"]
                    elif cmd == 'last':
                        result = pkg.openai.session.get_session(session_name).last_session()
                        if result is None:
                            reply = ["[bot]没有前一次的对话"]
                        else:
                            datetime_str = datetime.datetime.fromtimestamp(result.create_timestamp).strftime(
                                '%Y-%m-%d %H:%M:%S')
                            reply = ["[bot]已切换到前一次的对话：\n创建时间:{}\n".format(
                                datetime_str) + result.prompt[
                                                :min(100,
                                                     len(result.prompt))] + \
                                     ("..." if len(result.prompt) > 100 else "#END#")]
                    elif cmd == 'next':
                        result = pkg.openai.session.get_session(session_name).next_session()
                        if result is None:
                            reply = ["[bot]没有后一次的对话"]
                        else:
                            datetime_str = datetime.datetime.fromtimestamp(result.create_timestamp).strftime(
                                '%Y-%m-%d %H:%M:%S')
                            reply = ["[bot]已切换到后一次的对话：\n创建时间:{}\n".format(
                                datetime_str) + result.prompt[
                                                :min(100,
                                                     len(result.prompt))] + \
                                     ("..." if len(result.prompt) > 100 else "#END#")]
                    elif cmd == 'prompt':
                        reply = ["[bot]当前对话所有内容：\n" + pkg.openai.session.get_session(session_name).prompt]
                    elif cmd == 'list':
                        pkg.openai.session.get_session(session_name).persistence()
                        page = 0

                        if len(params) > 0:
                            try:
                                page = int(params[0])
                            except ValueError:
                                pass

                        results = pkg.openai.session.get_session(session_name).list_history(page=page)
                        if len(results) == 0:
                            reply = ["[bot]第{}页没有历史会话".format(page)]
                        else:
                            reply_str = "[bot]历史会话 第{}页：\n".format(page)
                            current = -1
                            for i in range(len(results)):
                                # 时间(使用create_timestamp转换) 序号 部分内容
                                datetime_obj = datetime.datetime.fromtimestamp(results[i]['create_timestamp'])
                                reply_str += "#{} 创建:{} {}\n".format(i + page * 10,
                                                                       datetime_obj.strftime("%Y-%m-%d %H:%M:%S"),
                                                                       results[i]['prompt'][
                                                                       :min(20, len(results[i]['prompt']))])
                                if results[i]['create_timestamp'] == pkg.openai.session.get_session(
                                        session_name).create_timestamp:
                                    current = i + page * 10

                            reply_str += "\n以上信息倒序排列"
                            if current != -1:
                                reply_str += ",当前会话是 #{}\n".format(current)
                            else:
                                reply_str += ",当前处于全新会话或不在此页"

                            reply = [reply_str]
                    elif cmd == 'usage':
                        api_keys = pkg.openai.manager.get_inst().key_mgr.api_key
                        reply_str = "[bot]api-key使用情况:(阈值:{})\n\n".format(
                            pkg.openai.manager.get_inst().key_mgr.api_key_fee_threshold)

                        using_key_name = ""
                        for api_key in api_keys:
                            reply_str += "{}:\n - {}美元 {}%\n".format(api_key,
                                                                       round(
                                                                           pkg.openai.manager.get_inst().key_mgr.get_fee(
                                                                               api_keys[api_key]), 6),
                                                                       round(
                                                                           pkg.openai.manager.get_inst().key_mgr.get_fee(
                                                                               api_keys[
                                                                                   api_key]) / pkg.openai.manager.get_inst().key_mgr.api_key_fee_threshold * 100,
                                                                           3))
                            if api_keys[api_key] == pkg.openai.manager.get_inst().key_mgr.using_key:
                                using_key_name = api_key
                        reply_str += "\n当前使用:{}".format(using_key_name)

                        reply = [reply_str]

                    elif cmd == 'draw':
                        if len(params) == 0:
                            reply = ["[bot]err:请输入图片描述文字"]
                        else:
                            session = pkg.openai.session.get_session(session_name)

                            res = session.draw_image(" ".join(params))

                            logging.debug("draw_image result:{}".format(res))
                            reply = [Image(url=res['data'][0]['url'])]
                            if not (hasattr(config, 'include_image_description')
                                    and not config.include_image_description):
                                reply.append(" ".join(params))
                except Exception as e:
                    mgr.notify_admin("{}指令执行失败:{}".format(session_name, e))
                    logging.exception(e)
                    reply = ["[bot]err:{}".format(e)]
            else:  # 消息
                logging.info("[{}]发送消息:{}".format(session_name, text_message[:min(20, len(text_message))] + (
                    "..." if len(text_message) > 20 else "")))

                session = pkg.openai.session.get_session(session_name)
                try:
                    prefix = "[GPT]" if hasattr(config, "show_prefix") and config.show_prefix else ""
                    reply = [prefix + session.append(text_message)]
                except openai.error.APIConnectionError as e:
                    mgr.notify_admin("{}会话调用API失败:{}".format(session_name, e))
                    reply = ["[bot]err:调用API失败，请重试或联系作者，或等待修复"]
                except openai.error.RateLimitError as e:
                    # 尝试切换api-key
                    current_tokens_amt = pkg.openai.manager.get_inst().key_mgr.get_fee(
                        pkg.openai.manager.get_inst().key_mgr.get_using_key())
                    pkg.openai.manager.get_inst().key_mgr.set_current_exceeded()
                    switched, name = pkg.openai.manager.get_inst().key_mgr.auto_switch()

                    if not switched:
                        mgr.notify_admin("API调用额度超限({}),请向OpenAI账户充值或在config.py中更换api_key".format(
                            current_tokens_amt))
                        reply = ["[bot]err:API调用额度超额，请联系作者，或等待修复"]
                    else:
                        openai.api_key = pkg.openai.manager.get_inst().key_mgr.get_using_key()
                        mgr.notify_admin("API调用额度超限({}),已切换到{}".format(current_tokens_amt, name))
                        reply = ["[bot]err:API调用额度超额，已自动切换，请重新发送消息"]
                except openai.error.InvalidRequestError as e:
                    mgr.notify_admin("{}API调用参数错误:{}\n\n这可能是由于config.py中的prompt_submit_length参数或"
                                     "completion_api_params中的max_tokens参数数值过大导致的，请尝试将其降低".format(
                        session_name, e))
                    reply = ["[bot]err:API调用参数错误，请联系作者，或等待修复"]
                except openai.error.ServiceUnavailableError as e:
                    # mgr.notify_admin("{}API调用服务不可用:{}".format(session_name, e))
                    reply = ["[bot]err:API调用服务暂不可用，请尝试重试"]
                except Exception as e:
                    logging.exception(e)
                    reply = ["[bot]err:{}".format(e)]

            if reply is not None and type(reply[0]) == str:
                logging.info(
                    "回复[{}]文字消息:{}".format(session_name,
                                                 reply[0][:min(100, len(reply[0]))] + (
                                                     "..." if len(reply[0]) > 100 else "")))
                reply = [mgr.reply_filter.process(reply[0])]
            else:
                logging.info("回复[{}]图片消息:{}".format(session_name, reply))

        finally:
            processing.remove(session_name)
    finally:
        pkg.openai.session.get_session(session_name).release_response_lock()

        return MessageChain(reply)