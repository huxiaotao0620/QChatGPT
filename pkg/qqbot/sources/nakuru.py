import mirai

from ..adapter import MessageSourceAdapter, MessageConverter, EventConverter
import nakuru
import nakuru.entities.components as nkc

import asyncio
import typing
import traceback
import logging
import json


class NakuruProjectMessageConverter(MessageConverter):
    """消息转换器"""
    @staticmethod
    def yiri2target(message_chain: mirai.MessageChain) -> list:
        msg_list = []
        if type(message_chain) is mirai.MessageChain:
            msg_list = message_chain.__root__
        elif type(message_chain) is list:
            msg_list = message_chain
        else:
            raise Exception("Unknown message type: " + str(message_chain) + type(message_chain))
        
        nakuru_msg_list = []
        
        # 遍历并转换
        for component in msg_list:
            if type(component) is mirai.Plain:
                nakuru_msg_list.append(nkc.Plain(component.text))
            elif type(component) is mirai.Image:
                if component.url is not None:
                    nakuru_msg_list.append(nkc.Image.fromURL(component.url))
                elif component.base64 is not None:
                    nakuru_msg_list.append(nkc.Image.fromBase64(component.base64))
                elif component.path is not None:
                    nakuru_msg_list.append(nkc.Image.fromFileSystem(component.path))
            elif type(component) is mirai.Face:
                nakuru_msg_list.append(nkc.Face(id=component.face_id))
            elif type(component) is mirai.At:
                nakuru_msg_list.append(nkc.At(qq=component.target))
            elif type(component) is mirai.AtAll:
                nakuru_msg_list.append(nkc.AtAll())
            elif type(component) is mirai.Voice:
                pass
            else:
                pass
        
        return nakuru_msg_list

    @staticmethod
    def target2yiri(message_chain: typing.Any, message_id: int = -1) -> mirai.MessageChain:
        """将Yiri的消息链转换为YiriMirai的消息链"""
        assert type(message_chain) is list

        yiri_msg_list = []
        import datetime
        # 添加Source组件以标记message_id等信息
        yiri_msg_list.append(mirai.models.message.Source(id=message_id, time=datetime.datetime.now()))
        for component in message_chain:
            if type(component) is nkc.Plain:
                yiri_msg_list.append(mirai.Plain(text=component.text))
            elif type(component) is nkc.Image:
                yiri_msg_list.append(mirai.Image(url=component.url))
            elif type(component) is nkc.Face:
                yiri_msg_list.append(mirai.Face(face_id=component.id))
            elif type(component) is nkc.At:
                yiri_msg_list.append(mirai.At(target=component.qq))
            elif type(component) is nkc.AtAll:
                yiri_msg_list.append(mirai.AtAll())
            else:
                pass
        logging.debug("转换后的消息链: " + str(yiri_msg_list))
        chain = mirai.MessageChain(yiri_msg_list)
        return chain


class NakuruProjectEventConverter(EventConverter):
    """事件转换器"""
    @staticmethod
    def yiri2target(event: typing.Type[mirai.Event]):
        if event is mirai.GroupMessage:
            return nakuru.GroupMessage
        elif event is mirai.FriendMessage:
            return nakuru.FriendMessage
        else:
            raise Exception("未支持转换的事件类型: " + str(event))

    @staticmethod
    def target2yiri(event: typing.Any) -> mirai.Event:
        yiri_chain = NakuruProjectMessageConverter.target2yiri(event.message, event.message_id)
        if type(event) is nakuru.FriendMessage:  # 私聊消息事件
            return mirai.FriendMessage(
                sender=mirai.models.entities.Friend(
                    id=event.sender.user_id,
                    nickname=event.sender.nickname,
                    remark=event.sender.nickname
                ),
                message_chain=yiri_chain,
                time=event.time
            )
        elif type(event) is nakuru.GroupMessage:  # 群聊消息事件
            permission = "MEMBER"

            if event.sender.role == "admin":
                permission = "ADMINISTRATOR"
            elif event.sender.role == "owner":
                permission = "OWNER"

            import mirai.models.entities as entities
            return mirai.GroupMessage(
                sender=mirai.models.entities.GroupMember(
                    id=event.sender.user_id,
                    member_name=event.sender.nickname,
                    permission=permission,
                    group=mirai.models.entities.Group(
                        id=event.group_id,
                        name=event.sender.nickname,
                        permission=entities.Permission.Member
                    ),
                    special_title=event.sender.title,
                    join_timestamp=0,
                    last_speak_timestamp=0,
                    mute_time_remaining=0,
                ),
                message_chain=yiri_chain,
                time=event.time
            )
        else:
            raise Exception("未支持转换的事件类型: " + str(event))



class NakuruProjectAdapter(MessageSourceAdapter):
    """nakuru-project适配器"""
    bot: nakuru.CQHTTP
    bot_account_id: int

    message_converter: NakuruProjectMessageConverter = NakuruProjectMessageConverter()
    event_converter: NakuruProjectEventConverter = NakuruProjectEventConverter()

    listener_list: list[dict]

    def __init__(self, cfg: dict):
        """初始化nakuru-project的对象"""
        self.bot = nakuru.CQHTTP(**cfg)
        self.listener_list = []
        # nakuru库有bug，这个接口没法带access_token，会失败
        # 所以目前自行发请求
        import config
        import requests
        resp = requests.get(
            url="http://{}:{}/get_login_info".format(config.nakuru_config['host'], config.nakuru_config['http_port']),
            headers={
                'Authorization': "Bearer " + config.nakuru_config['token'] if 'token' in config.nakuru_config else ""
            },
            timeout=5
        )
        self.bot_account_id = int(resp.json()['data']['user_id'])

    def send_message(
        self,
        target_type: str,
        target_id: str,
        message: mirai.MessageChain
    ):
        task = None
        if target_type == "group":
            task = self.bot.sendGroupMessage(int(target_id), self.message_converter.yiri2target(message))
        elif target_type == "person":
            task = self.bot.sendFriendMessage(int(target_id), self.message_converter.yiri2target(message))
        else:
            raise Exception("Unknown target type: " + target_type)

        asyncio.run(task)

    def reply_message(
        self,
        message_source: mirai.MessageEvent,
        message: mirai.MessageChain,
        quote_origin: bool = False
    ):
        message = self.message_converter.yiri2target(message)
        if quote_origin:
            # 在前方添加引用组件
            message.insert(0, nkc.Reply(
                    id=message_source.message_chain.message_id,
                )
            )
        if type(message_source) is mirai.GroupMessage:
            task = self.bot.sendGroupMessage(
                message_source.sender.group.id,
                message,
                # quote=message_source.message_id if quote_origin else None
            )
        elif type(message_source) is mirai.FriendMessage:
            task = self.bot.sendFriendMessage(
                message_source.sender.id,
                message,
                # quote=message_source.message_id if quote_origin else None
            )
        else:
            raise Exception("Unknown message source type: " + str(type(message_source)))

        asyncio.run(task)

    def is_muted(self, group_id: int) -> bool:
        import time
        # 检查是否被禁言
        group_member_info = asyncio.run(self.bot.getGroupMemberInfo(group_id, self.bot_account_id))
        return group_member_info.shut_up_timestamp > int(time.time())

    def register_listener(
        self,
        event_type: typing.Type[mirai.Event],
        callback: typing.Callable[[mirai.Event], None]
    ):
        try:
            logging.debug("注册监听器: " + str(event_type) + " -> " + str(callback))

            # 包装函数
            async def listener_wrapper(app: nakuru.CQHTTP, source: self.event_converter.yiri2target(event_type)):
                callback(self.event_converter.target2yiri(source))

            # 将包装函数和原函数的对应关系存入列表
            self.listener_list.append(
                {
                    "event_type": event_type,
                    "callable": callback,
                    "wrapper": listener_wrapper,
                }
            )

            # 注册监听器
            self.bot.receiver(self.event_converter.yiri2target(event_type).__name__)(listener_wrapper)
            logging.debug("注册完成")
        except Exception as e:
            traceback.print_exc()
            raise e

    def unregister_listener(
        self,
        event_type: typing.Type[mirai.Event],
        callback: typing.Callable[[mirai.Event], None]
    ):
        nakuru_event_name = self.event_converter.yiri2target(event_type).__name__

        new_event_list = []

        # 从本对象的监听器列表中查找并删除
        target_wrapper = None
        for listener in self.listener_list:
            if listener["event_type"] == event_type and listener["callable"] == callback:
                target_wrapper = listener["wrapper"]
                self.listener_list.remove(listener)
                break

        if target_wrapper is None:
            raise Exception("未找到对应的监听器")

        for func in self.bot.event[nakuru_event_name]:
            if func.callable != target_wrapper:
                new_event_list.append(func)

        self.bot.event[nakuru_event_name] = new_event_list

    def run_sync(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot.run()

    def kill(self) -> bool:
        return False
