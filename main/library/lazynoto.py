"""
LazyNoto - Telegram Bot Framework & Helper Library
Built on top of python-telegram-bot (PTB) v20+ / v21+
Designed with clean type-hinting, FSM, middleware, retry handling,
media helpers, keyboard builders, and high developer ergonomics.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import (
    Any,
    BinaryIO,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from telegram import (
    CallbackQuery,
    Chat,
    ChatMember,
    File,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    Message,
    MessageId,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User,
    WebAppInfo,
)
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger("LazyNoto")


# =====================================================================
# Types & Aliases
# =====================================================================

Handler = Callable[["NotoContext"], Coroutine[Any, Any, Any]]
Middleware = Callable[["NotoContext"], Coroutine[Any, Any, bool]]
ErrorHandler = Callable[["NotoContext", Exception], Coroutine[Any, Any, Any]]
PTBCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Coroutine[Any, Any, None],
]

MediaInput = Union[str, bytes, BinaryIO, Path, InputFile]
Markup = Union[
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
]


def retry_delay(value: Union[int, float, timedelta]) -> float:
    """Convert RetryAfter duration to seconds safely."""
    if isinstance(value, timedelta):
        return max(0.0, value.total_seconds())
    return max(0.0, float(value))


# =====================================================================
# Keyboard Builders
# =====================================================================


class InlineMenu:
    """Fluent builder for Telegram inline keyboards."""

    def __init__(self) -> None:
        self.rows: List[List[InlineKeyboardButton]] = []

    def button(
        self,
        text: str,
        callback_data: Optional[str] = None,
        url: Optional[str] = None,
        web_app_url: Optional[str] = None,
    ) -> "InlineMenu":
        if callback_data is None and url is None and web_app_url is None:
            raise ValueError(
                "One of callback_data, url, or web_app_url is required."
            )

        btn = InlineKeyboardButton(
            text=text,
            callback_data=callback_data,
            url=url,
            web_app=WebAppInfo(url=web_app_url) if web_app_url is not None else None,
        )
        self.rows.append([btn])
        return self

    def row(self, *buttons: InlineKeyboardButton) -> "InlineMenu":
        """Add an already-created row of Telegram buttons."""
        if not buttons:
            raise ValueError("A row must contain at least one button.")
        self.rows.append(list(buttons))
        return self

    def add_row_buttons(
        self,
        button_list: Sequence[Tuple[str, str]],
    ) -> "InlineMenu":
        """Add a row from (label, callback_data) pairs."""
        if not button_list:
            return self

        row_items = [
            InlineKeyboardButton(text=label, callback_data=cb)
            for label, cb in button_list
        ]
        self.rows.append(row_items)
        return self

    def grid(
        self,
        buttons: Sequence[Tuple[str, str]],
        cols: int = 2,
    ) -> "InlineMenu":
        """Arrange (label, callback_data) pairs in a grid."""
        if cols < 1:
            raise ValueError("cols must be greater than zero.")

        current_row: List[InlineKeyboardButton] = []
        for label, cb in buttons:
            current_row.append(
                InlineKeyboardButton(text=label, callback_data=cb)
            )
            if len(current_row) == cols:
                self.rows.append(current_row)
                current_row = []

        if current_row:
            self.rows.append(current_row)

        return self

    def clear(self) -> "InlineMenu":
        """Remove all buttons."""
        self.rows.clear()
        return self

    def build(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=self.rows)


class ReplyMenu:
    """Fluent builder for Telegram reply keyboards."""

    def __init__(
        self,
        resize_keyboard: bool = True,
        one_time_keyboard: bool = False,
        is_persistent: bool = False,
    ) -> None:
        self.rows: List[List[KeyboardButton]] = []
        self.resize_keyboard = resize_keyboard
        self.one_time_keyboard = one_time_keyboard
        self.is_persistent = is_persistent

    def button(
        self,
        text: str,
        request_contact: bool = False,
        request_location: bool = False,
    ) -> "ReplyMenu":
        btn = KeyboardButton(
            text=text,
            request_contact=request_contact,
            request_location=request_location,
        )
        self.rows.append([btn])
        return self

    def row(self, *texts: str) -> "ReplyMenu":
        if not texts:
            raise ValueError("A row must contain at least one text.")
        self.rows.append([KeyboardButton(text=t) for t in texts])
        return self

    def grid(
        self,
        texts: Sequence[str],
        cols: int = 2,
    ) -> "ReplyMenu":
        """Arrange button texts in an N-column grid."""
        if cols < 1:
            raise ValueError("cols must be greater than zero.")

        current_row: List[KeyboardButton] = []
        for text in texts:
            current_row.append(KeyboardButton(text=text))
            if len(current_row) == cols:
                self.rows.append(current_row)
                current_row = []

        if current_row:
            self.rows.append(current_row)

        return self

    def build(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=self.rows,
            resize_keyboard=self.resize_keyboard,
            one_time_keyboard=self.one_time_keyboard,
            is_persistent=self.is_persistent,
        )


# =====================================================================
# State Manager (In-Memory FSM)
# =====================================================================


class StateManager:
    """In-memory FSM and per-user data manager."""

    def __init__(self) -> None:
        self._states: Dict[int, Optional[str]] = {}
        self._data: Dict[int, Dict[str, Any]] = {}

    async def set_state(self, user_id: int, state: Optional[str]) -> None:
        if state is None:
            self._states.pop(user_id, None)
        else:
            self._states[user_id] = state

    async def get_state(self, user_id: int) -> Optional[str]:
        return self._states.get(user_id)

    async def clear_state(self, user_id: int) -> None:
        self._states.pop(user_id, None)

    async def set_data(self, user_id: int, key: str, value: Any) -> None:
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id][key] = value

    async def get_data(self, user_id: int, key: str, default: Any = None) -> Any:
        return self._data.get(user_id, {}).get(key, default)

    async def get_all_data(self, user_id: int) -> Dict[str, Any]:
        return dict(self._data.get(user_id, {}))

    async def clear_data(self, user_id: int) -> None:
        self._data.pop(user_id, None)

    async def clear_user(self, user_id: int) -> None:
        await self.clear_state(user_id)
        await self.clear_data(user_id)


# =====================================================================
# Context Wrapper
# =====================================================================


class NotoContext:
    """High-level wrapper around PTB Update and CallbackContext."""

    def __init__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        app: "LazyNoto",
    ) -> None:
        self.update = update
        self.context = context
        self.app = app

        self.user: Optional[User] = update.effective_user
        self.chat: Optional[Chat] = update.effective_chat
        self.message: Optional[Message] = update.effective_message
        self.callback_query: Optional[CallbackQuery] = update.callback_query

        self.user_id: int = self.user.id if self.user else 0
        self.chat_id: int = self.chat.id if self.chat else 0

        self.text: str = ""
        if self.message is not None:
            self.text = self.message.text or self.message.caption or ""

        self.data: str = ""
        if self.callback_query is not None and self.callback_query.data is not None:
            self.data = self.callback_query.data

        self.args: List[str] = list(context.args or [])
        self.web_app_data: Optional[Dict[str, Any]] = self._parse_web_app_data()

    # -----------------------------------------------------------------
    # Basic Helpers
    # -----------------------------------------------------------------

    @property
    def query(self) -> str:
        """Return command arguments as a single string."""
        return " ".join(self.args)

    @property
    def first_name(self) -> str:
        return self.user.first_name if self.user else ""

    @property
    def username(self) -> str:
        if self.user is None or self.user.username is None:
            return ""
        return self.user.username

    # -----------------------------------------------------------------
    # Parsing
    # -----------------------------------------------------------------

    def _parse_web_app_data(self) -> Optional[Dict[str, Any]]:
        if self.message is None or self.message.web_app_data is None:
            return None

        raw_data = self.message.web_app_data.data
        try:
            parsed: Any = json.loads(raw_data)
        except json.JSONDecodeError:
            return {"raw": raw_data}

        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}

    # -----------------------------------------------------------------
    # Chat Information
    # -----------------------------------------------------------------

    @property
    def is_private(self) -> bool:
        return bool(self.chat is not None and self.chat.type == ChatType.PRIVATE)

    @property
    def is_group(self) -> bool:
        return bool(
            self.chat is not None
            and self.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}
        )

    @property
    def is_channel(self) -> bool:
        return bool(self.chat is not None and self.chat.type == ChatType.CHANNEL)

    @property
    def is_admin(self) -> bool:
        return self.user_id in self.app.admin_ids

    # -----------------------------------------------------------------
    # FSM Helpers
    # -----------------------------------------------------------------

    async def get_state(self) -> Optional[str]:
        return await self.app.state_manager.get_state(self.user_id)

    async def set_state(self, state: Optional[str]) -> None:
        await self.app.state_manager.set_state(self.user_id, state)

    async def clear_state(self) -> None:
        await self.app.state_manager.clear_state(self.user_id)

    async def set_data(self, key: str, value: Any) -> None:
        await self.app.state_manager.set_data(self.user_id, key, value)

    async def get_data(self, key: str, default: Any = None) -> Any:
        return await self.app.state_manager.get_data(self.user_id, key, default)

    async def get_all_data(self) -> Dict[str, Any]:
        return await self.app.state_manager.get_all_data(self.user_id)

    async def clear_data(self) -> None:
        await self.app.state_manager.clear_data(self.user_id)

    # -----------------------------------------------------------------
    # Markup Helpers
    # -----------------------------------------------------------------

    def _resolve_markup(
        self,
        inline: Optional[InlineMenu] = None,
        reply_menu: Optional[ReplyMenu] = None,
        remove_keyboard: bool = False,
    ) -> Optional[Markup]:
        if inline is not None:
            return inline.build()
        if reply_menu is not None:
            return reply_menu.build()
        if remove_keyboard:
            return ReplyKeyboardRemove()
        return None

    # -----------------------------------------------------------------
    # Chat Actions
    # -----------------------------------------------------------------

    async def send_action(
        self,
        action: Union[ChatAction, str] = ChatAction.TYPING,
    ) -> bool:
        if not self.chat_id:
            return False
        try:
            await self.context.bot.send_chat_action(
                chat_id=self.chat_id,
                action=action,
            )
            return True
        except TelegramError as exc:
            logger.debug("Chat action failed: %s", exc)
            return False

    async def typing(self) -> bool:
        return await self.send_action(ChatAction.TYPING)

    async def uploading_photo(self) -> bool:
        return await self.send_action(ChatAction.UPLOAD_PHOTO)

    async def uploading_video(self) -> bool:
        return await self.send_action(ChatAction.UPLOAD_VIDEO)

    async def uploading_document(self) -> bool:
        return await self.send_action(ChatAction.UPLOAD_DOCUMENT)

    async def recording_voice(self) -> bool:
        return await self.send_action(ChatAction.RECORD_VOICE)

    # -----------------------------------------------------------------
    # Text Messaging
    # -----------------------------------------------------------------

    async def reply(
        self,
        text: str,
        inline: Optional[InlineMenu] = None,
        reply_menu: Optional[ReplyMenu] = None,
        remove_keyboard: bool = False,
        parse_mode: Optional[str] = ParseMode.HTML,
        disable_web_page_preview: bool = True,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = self._resolve_markup(
            inline=inline,
            reply_menu=reply_menu,
            remove_keyboard=remove_keyboard,
        )

        try:
            return await self.context.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except RetryAfter as exc:
            await asyncio.sleep(retry_delay(exc.retry_after))
            return await self.reply(
                text=text,
                inline=inline,
                reply_menu=reply_menu,
                remove_keyboard=remove_keyboard,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except TelegramError as exc:
            logger.error("Error in reply: %s", exc)
            return None

    async def send(
        self,
        text: str,
        inline: Optional[InlineMenu] = None,
        reply_menu: Optional[ReplyMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        return await self.reply(
            text=text,
            inline=inline,
            reply_menu=reply_menu,
            parse_mode=parse_mode,
        )

    async def reply_to(
        self,
        text: str,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id or self.message is None:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=markup,
                reply_to_message_id=self.message.message_id,
            )
        except TelegramError as exc:
            logger.error("Error in reply_to: %s", exc)
            return None

    # -----------------------------------------------------------------
    # Callback and Message Editing
    # -----------------------------------------------------------------

    async def edit(
        self,
        text: str,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Union[Message, bool]]:
        if self.callback_query is None or self.callback_query.message is None:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.callback_query.edit_message_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except RetryAfter as exc:
            await asyncio.sleep(retry_delay(exc.retry_after))
            return await self.edit(
                text=text,
                inline=inline,
                parse_mode=parse_mode,
            )
        except TelegramError as exc:
            logger.error("Error in edit: %s", exc)
            return None

    async def answer_callback(
        self,
        text: Optional[str] = None,
        show_alert: bool = False,
        cache_time: int = 0,
    ) -> bool:
        if self.callback_query is None:
            return False

        try:
            await self.callback_query.answer(
                text=text,
                show_alert=show_alert,
                cache_time=cache_time,
            )
            return True
        except TelegramError as exc:
            logger.error("Error in answer_callback: %s", exc)
            return False

    # -----------------------------------------------------------------
    # Message Operations
    # -----------------------------------------------------------------

    async def delete(self) -> bool:
        if not self.chat_id or self.message is None:
            return False

        try:
            result = await self.context.bot.delete_message(
                chat_id=self.chat_id,
                message_id=self.message.message_id,
            )
            return bool(result)
        except TelegramError as exc:
            logger.error("Error in delete: %s", exc)
            return False

    async def forward(self, to_chat_id: int) -> Optional[Message]:
        if not self.chat_id or self.message is None:
            return None

        try:
            return await self.context.bot.forward_message(
                chat_id=to_chat_id,
                from_chat_id=self.chat_id,
                message_id=self.message.message_id,
            )
        except TelegramError as exc:
            logger.error("Error in forward: %s", exc)
            return None

    async def copy_to(self, to_chat_id: int) -> Optional[MessageId]:
        if not self.chat_id or self.message is None:
            return None

        try:
            return await self.context.bot.copy_message(
                chat_id=to_chat_id,
                from_chat_id=self.chat_id,
                message_id=self.message.message_id,
            )
        except TelegramError as exc:
            logger.error("Error in copy_to: %s", exc)
            return None

    async def pin(self, disable_notification: bool = False) -> bool:
        if not self.chat_id or self.message is None:
            return False

        try:
            result = await self.context.bot.pin_chat_message(
                chat_id=self.chat_id,
                message_id=self.message.message_id,
                disable_notification=disable_notification,
            )
            return bool(result)
        except TelegramError as exc:
            logger.error("Error in pin: %s", exc)
            return False

    async def unpin(self) -> bool:
        if not self.chat_id:
            return False

        try:
            result = await self.context.bot.unpin_chat_message(
                chat_id=self.chat_id,
            )
            return bool(result)
        except TelegramError as exc:
            logger.error("Error in unpin: %s", exc)
            return False

    # -----------------------------------------------------------------
    # Media Helpers
    # -----------------------------------------------------------------

    async def send_photo(
        self,
        photo: MediaInput,
        caption: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_photo(
                chat_id=self.chat_id,
                photo=photo,  # type: ignore[arg-type]
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_photo: %s", exc)
            return None

    async def send_document(
        self,
        document: MediaInput,
        caption: Optional[str] = None,
        filename: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_document(
                chat_id=self.chat_id,
                document=document,  # type: ignore[arg-type]
                caption=caption,
                filename=filename,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_document: %s", exc)
            return None

    async def send_voice(
        self,
        voice: MediaInput,
        caption: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_voice(
                chat_id=self.chat_id,
                voice=voice,  # type: ignore[arg-type]
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_voice: %s", exc)
            return None

    async def send_video(
        self,
        video: MediaInput,
        caption: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_video(
                chat_id=self.chat_id,
                video=video,  # type: ignore[arg-type]
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_video: %s", exc)
            return None

    async def send_audio(
        self,
        audio: MediaInput,
        caption: Optional[str] = None,
        title: Optional[str] = None,
        performer: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_audio(
                chat_id=self.chat_id,
                audio=audio,  # type: ignore[arg-type]
                caption=caption,
                title=title,
                performer=performer,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_audio: %s", exc)
            return None

    async def send_animation(
        self,
        animation: MediaInput,
        caption: Optional[str] = None,
        inline: Optional[InlineMenu] = None,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Optional[Message]:
        if not self.chat_id:
            return None

        markup = inline.build() if inline else None
        try:
            return await self.context.bot.send_animation(
                chat_id=self.chat_id,
                animation=animation,  # type: ignore[arg-type]
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramError as exc:
            logger.error("Error in send_animation: %s", exc)
            return None

    # -----------------------------------------------------------------
    # Telegram API Helpers
    # -----------------------------------------------------------------

    async def get_file(self, file_id: str) -> Optional[File]:
        try:
            return await self.context.bot.get_file(file_id)
        except TelegramError as exc:
            logger.error("Error in get_file: %s", exc)
            return None

    async def get_chat_member(self, user_id: int) -> Optional[ChatMember]:
        if not self.chat_id:
            return None

        try:
            return await self.context.bot.get_chat_member(
                chat_id=self.chat_id,
                user_id=user_id,
            )
        except TelegramError as exc:
            logger.error("Error in get_chat_member: %s", exc)
            return None


# =====================================================================
# Main Application
# =====================================================================


class LazyNoto:
    """Central application wrapper for Telegram bots."""

    def __init__(
        self,
        token: str,
        admin_ids: Optional[Sequence[int]] = None,
    ) -> None:
        self.token = token
        self.admin_ids: Set[int] = set(admin_ids or [])

        self.state_manager = StateManager()
        self._app: Application = ApplicationBuilder().token(token).build()

        self._middlewares: List[Middleware] = []
        self._state_handlers: Dict[str, Handler] = {}
        self._error_handler: Optional[ErrorHandler] = None

    # -----------------------------------------------------------------
    # Middleware
    # -----------------------------------------------------------------

    def middleware(self, func: Middleware) -> Middleware:
        """Register middleware executed before handlers."""
        self._middlewares.append(func)
        return func

    async def _run_middlewares(self, ctx: NotoContext) -> bool:
        for m in self._middlewares:
            try:
                allowed = await m(ctx)
            except Exception as exc:
                logger.exception("Middleware failed: %s", exc)
                return False

            if not allowed:
                return False

        return True

    # -----------------------------------------------------------------
    # Wrapper
    # -----------------------------------------------------------------

    def _wrap(
        self,
        handler: Handler,
        admin_only: bool = False,
    ) -> PTBCallback:
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
        ) -> None:
            ctx = NotoContext(
                update=update,
                context=context,
                app=self,
            )

            if admin_only and not ctx.is_admin:
                logger.warning("Unauthorized access from user %s", ctx.user_id)
                return

            if not await self._run_middlewares(ctx):
                return

            user_state = await ctx.get_state()
            target_handler = handler

            is_command = ctx.text.startswith("/") if ctx.text else False

            if (
                user_state is not None
                and user_state in self._state_handlers
                and not is_command
            ):
                target_handler = self._state_handlers[user_state]

            try:
                await target_handler(ctx)
            except Exception as exc:
                if self._error_handler is not None:
                    await self._error_handler(ctx, exc)
                else:
                    logger.exception("Unhandled LazyNoto error: %s", exc)

        return wrapper

    # -----------------------------------------------------------------
    # Registration Decorators
    # -----------------------------------------------------------------

    def command(
        self,
        name: str,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                CommandHandler(
                    command=name,
                    callback=self._wrap(func, admin_only=admin_only),
                )
            )
            return func

        return decorator

    def on_message(
        self,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    self._wrap(func, admin_only=admin_only),
                )
            )
            return func

        return decorator

    def on_photo(
        self,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                MessageHandler(
                    filters.PHOTO,
                    self._wrap(func, admin_only=admin_only),
                )
            )
            return func

        return decorator

    def on_document(
        self,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                MessageHandler(
                    filters.Document.ALL,
                    self._wrap(func, admin_only=admin_only),
                )
            )
            return func

        return decorator

    def on_voice(
        self,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                MessageHandler(
                    filters.VOICE,
                    self._wrap(func, admin_only=admin_only),
                )
            )
            return func

        return decorator

    def on_callback(
        self,
        pattern: Optional[str] = None,
        admin_only: bool = False,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._app.add_handler(
                CallbackQueryHandler(
                    callback=self._wrap(func, admin_only=admin_only),
                    pattern=pattern,
                )
            )
            return func

        return decorator

    def on_state(
        self,
        state_name: str,
    ) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._state_handlers[state_name] = func
            return func

        return decorator

    def error(self) -> Callable[[ErrorHandler], ErrorHandler]:
        def decorator(func: ErrorHandler) -> ErrorHandler:
            self._error_handler = func
            return func

        return decorator

    # -----------------------------------------------------------------
    # Utilities & Lifecycle
    # -----------------------------------------------------------------

    def add_handler(self, handler: Any, group: int = 0) -> None:
        """Add a native PTB handler when needed."""
        self._app.add_handler(handler, group=group)

    def remove_handler(self, handler: Any, group: int = 0) -> None:
        self._app.remove_handler(handler, group=group)

    def run(self) -> None:
        """Start polling synchronously."""
        logger.info("Starting LazyNoto Telegram Bot...")
        self._app.run_polling(drop_pending_updates=True)

    async def start(self) -> None:
        """Initialize and start the application asynchronously."""
        await self._app.initialize()
        await self._app.start()
        if self._app.updater is not None:
            await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop the application asynchronously."""
        if self._app.updater is not None:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()


# =====================================================================
# Factory
# =====================================================================


def create_bot(
    token: str,
    admin_ids: Optional[Sequence[int]] = None,
) -> LazyNoto:
    """Create and return a LazyNoto application."""
    return LazyNoto(
        token=token,
        admin_ids=admin_ids,
    )


__all__ = [
    "ErrorHandler",
    "Handler",
    "InlineMenu",
    "LazyNoto",
    "MediaInput",
    "Middleware",
    "NotoContext",
    "ReplyMenu",
    "StateManager",
    "create_bot",
    "retry_delay",
]
