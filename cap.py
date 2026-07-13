import asyncio
import random
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ChatJoinRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os

# --- Настройки ---
BOT_TOK = os.getenv("BOT_TOK")  # или вставь сюда: "твой_токен"
CHANNEL_ID = -1003679758252     # твой канал

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Инициализация ---
storage = MemoryStorage()
bot = Bot(token=BOT_TOK)
dp = Dispatcher(storage=storage)

# --- FSM состояния (можно не использовать, но оставим) ---
class CaptchaStates(StatesGroup):
    waiting_captcha = State()

# --- Хранилище данных капчи ---
user_captcha_data = {}

# --- Генерация капчи ---
def generate_captcha():
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    operation = random.choice(['+', '-'])
    if operation == '+':
        correct = a + b
        question = f"{a} + {b} = ?"
    else:
        if a < b:
            a, b = b, a
        correct = a - b
        question = f"{a} - {b} = ?"
    
    options = {correct}
    while len(options) < 4:
        fake = correct + random.randint(-10, 10)
        if fake != correct and fake >= 0:
            options.add(fake)
    options = list(options)
    random.shuffle(options)
    return question, correct, options

def captcha_keyboard(options):
    builder = InlineKeyboardBuilder()
    for val in options:
        builder.button(text=str(val), callback_data=f"captcha_{val}")
    builder.adjust(2)
    return builder.as_markup()

# --- Обработчик заявок на вступление ---
@dp.chat_join_request(F.chat.id == CHANNEL_ID)
async def handle_join_request(join_request: ChatJoinRequest, state: FSMContext):
    user_id = join_request.from_user.id
    if user_id in user_captcha_data:
        await bot.send_message(user_id, "Вы уже проходите капчу. Пожалуйста, завершите её.")
        return
    
    question, correct, options = generate_captcha()
    sent_msg = await bot.send_message(
        user_id,
        f"🛡️ Для подтверждения вступления в канал решите пример:\n\n{question}\n\nВыберите правильный ответ:",
        reply_markup=captcha_keyboard(options)
    )
    
    user_captcha_data[user_id] = {
        "answer": correct,
        "attempts": 0,
        "channel_id": join_request.chat.id,
        "message_id": sent_msg.message_id
    }
    
    await state.set_state(CaptchaStates.waiting_captcha)
    asyncio.create_task(auto_reject(user_id, 300))

async def auto_reject(user_id: int, timeout: int):
    await asyncio.sleep(timeout)
    data = user_captcha_data.get(user_id)
    if data:
        await bot.send_message(user_id, "⏰ Время на прохождение капчи истекло. Попробуйте подать заявку снова.")
        try:
            await bot.decline_chat_join_request(chat_id=data["channel_id"], user_id=user_id)
        except Exception as e:
            logging.error(f"Не удалось отклонить заявку: {e}")
        del user_captcha_data[user_id]

# --- Обработка нажатий на кнопки капчи (без StateFilter, чтобы гарантированно работать) ---
@dp.callback_query(F.data.startswith("captcha_"))
async def process_captcha(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = user_captcha_data.get(user_id)
    if not data:
        await callback.answer("❌ Ваша сессия истекла или заявка уже обработана.", show_alert=True)
        await callback.message.delete()
        await state.clear()
        return
    
    selected = int(callback.data.split("_")[1])
    correct = data["answer"]
    attempts = data["attempts"] + 1
    data["attempts"] = attempts
    channel_id = data["channel_id"]
    
    if selected == correct:
        await callback.answer("✅ Верно! Вы проходите в канал.", show_alert=True)
        await callback.message.delete()
        try:
            await bot.approve_chat_join_request(chat_id=channel_id, user_id=user_id)
            await bot.send_message(user_id, "🎉 Добро пожаловать в канал!")
        except Exception as e:
            logging.error(f"Ошибка при одобрении заявки: {e}")
            await bot.send_message(user_id, "⚠️ Произошла ошибка при обработке. Попробуйте позже.")
        del user_captcha_data[user_id]
        await state.clear()
    else:
        if attempts >= 3:
            await callback.answer("❌ Неверно. Попытки закончились.", show_alert=True)
            await callback.message.delete()
            try:
                await bot.decline_chat_join_request(chat_id=channel_id, user_id=user_id)
                await bot.send_message(user_id, "❌ Вы не прошли капчу. Подайте заявку заново.")
            except Exception as e:
                logging.error(f"Ошибка при отклонении: {e}")
            del user_captcha_data[user_id]
            await state.clear()
        else:
            await callback.answer(f"❌ Неверно. Осталось попыток: {3 - attempts}", show_alert=True)
            question, new_correct, options = generate_captcha()
            data["answer"] = new_correct
            await callback.message.edit_text(
                f"🛡️ Попробуйте снова:\n\n{question}",
                reply_markup=captcha_keyboard(options)
            )

# --- Команда /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Я бот для защиты канала от ботов. Подайте заявку на вступление, и я пришлю капчу.")

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
