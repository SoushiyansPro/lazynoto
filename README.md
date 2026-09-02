<div align="center">

  <img src="https://github.com/user-attachments/assets/logo-placeholder.png" width="200" alt="LazyNoto Logo" />

  <h1>⚡ LazyNoto Framework</h1>
  
  <p align="center">
    <b>The Next-Gen Async Python Framework for Telegram Bot Development.</b>
    <br />
    <i>Simple. Robust. High-Performance. Built for Scalability.</i>
  </p>

  <!-- Badges -->
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
    <img src="https://img.shields.io/badge/AsyncIO-Enabled-blueviolet?style=for-the-badge" />
    <img src="https://img.shields.io/badge/Telegram_Bot_API-v1.2-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" />
    <img src="https://img.shields.io/badge/License-MIT-success?style=for-the-badge" />
    <img src="https://img.shields.io/badge/Status-Stable-brightgreen?style=for-the-badge" />
  </p>

  <p align="center">
    <a href="#about">About</a> •
    <a href="#why-lazynoto">Why Us</a> •
    <a href="#architecture">Architecture</a> •
    <a href="#getting-started">Quickstart</a> •
    <a href="#fsm-engine">FSM</a> •
    <a href="#documentation">Documentation</a>
  </p>

</div>

---

## 🧐 About LazyNoto

**LazyNoto** یک فریم‌ورک کاملاً ناهمگام (Asynchronous) است که به طور اختصاصی برای توسعه‌دهندگان پایتون طراحی شده تا پیچیدگی‌های تعامل با Telegram Bot API را به حداقل برساند. در LazyNoto، تمرکز اصلی ما بر روی **"کدنویسی کمتر، خروجی بیشتر"** است. برخلاف کتابخانه‌های سنتی که شما را درگیر مدیریت دستی کانکشن‌ها و آرایه‌های پیچیده می‌کنند، LazyNoto با معرفی یک هسته هوشمند، پیچیدگی را به سطح انتزاع می‌برد.

---

## 🚀 Why LazyNoto? (تفاوت‌های بنیادین)

چرا باید از LazyNoto استفاده کنیم؟ پاسخ ساده است: **بهینه‌سازی زمان توسعه.**

*   **Fluent Interface Design:** با متدهای زنجیره‌ای (Chaining)، ساخت منوها و کیبوردها تبدیل به یک تجربه بصری شده است.
*   **Smart Anti-Crash Engine:** سیستم داخلی ما به‌طور خودکار `FloodWait` ها را مدیریت می‌کند و از کرش کردن ربات در مواجهه با خطاهای تلگرام جلوگیری می‌کند.
*   **NotoContext Object:** این قلب تپنده فریم‌ورک است؛ تمام چیزی که برای پردازش یک پیام نیاز دارید (اطلاعات کاربر، وضعیت چت، ابزارهای پاسخ، و داده‌های FSM) در `ctx` کپسوله شده است.
*   **Optimized Memory Usage:** طراحی سبک و بهینه شده برای اجرا روی سرورهای با منابع محدود (مثل VPS های ارزان).

---

## 🏗️ Technical Architecture (کالبدشکافی فنی)

LazyNoto بر پایه `asyncio` بنا شده و معماری آن به صورت زیر دسته‌بندی می‌شود:

1.  **Dispatcher Layer:** مسئول دریافت و توزیع رویدادها (Updates) با کمترین تأخیر.
2.  **State Machine (FSM):** یک دیتابیس داخلی برای مدیریت وضعیت کاربران (Context Persistence) که قابلیت اتصال به SQLite/Supabase را دارد.
3.  **Menu Builder:** موتور رندرینگ کیبورد که توابع پیچیده تلگرام را به خروجی `InlineKeyboardMarkup` تبدیل می‌کند.
4.  **Middleware Pipeline:** قابلیت اضافه کردن لایه‌های کنترلی (Auth, Logging, RateLimiting) قبل از رسیدن پیام به هندلر اصلی.

---

## ⚡ Quickstart: اولین قدم

نصب ساده است:
```bash
pip install lazynoto
```

ساده‌ترین نمونه کد برای یک ربات اکو (Echo Bot):

```python
from lazynoto import LazyNoto, NotoContext

bot = LazyNoto(token="YOUR_TOKEN")

@bot.command("start")
async def start(ctx: NotoContext):
    await ctx.reply("سلام! من با LazyNoto ساخته شدم. 🚀")

if __name__ == "__main__":
    bot.run()
```

---

## 🧠 Advanced FSM (ماشین وضعیت)

مدیریت مکالمات چندمرحله‌ای (مانند ثبت‌نام در سایت) در LazyNoto به شکل زیر است:

```python
@bot.command("register")
async def register(ctx: NotoContext):
    await ctx.set_state("ASK_NAME")
    await ctx.reply("نام خود را وارد کنید:")

@bot.on_state("ASK_NAME")
async def process_name(ctx: NotoContext):
    await ctx.set_data("name", ctx.text)
    await ctx.set_state("ASK_AGE")
    await ctx.reply("سن خود را وارد کنید:")
```

---

## 📂 Documentation (دانشنامه)

ما مستندات فنی بسیار دقیقی آماده کرده‌ایم. برای دسترسی به راهنمای جامع ۱۱ مرحله‌ای (شامل نصب، روتینگ، هندلرهای پیشرفته و دیباگینگ)، فایل **`docs.html`** را در پوشه پروژه باز کنید. این فایل مرجع رسمی توسعه‌دهندگان LazyNoto است.

---

## 🛠️ Roadmap (نقشه راه)

- [x] هسته اولیه AsyncIO و Dispatcher
- [x] سیستم منوساز زنجیره‌ای
- [x] ماشین وضعیت (FSM) داخلی
- [ ] اتصال مستقیم به Supabase (نسخه ۲.۰)
- [ ] داشبورد مانیتورینگ آنلاین (نسخه ۲.۱)
- [ ] تولیدکننده خودکار داکیومنت از روی هندلرها

---

## 🤝 Contribution & Support

از هرگونه مشارکت در LazyNoto استقبال می‌کنیم. اگر باگی پیدا کردید یا پیشنهادی برای بهبود دارید:

1. **Issues:** مشکل را در بخش Issues ثبت کنید.
2. **Pull Requests:** کد خود را بنویسید و PR بزنید.
3. **Communication:** برای گفتگوهای فنی و پشتیبانی با [@Soushiyans_Pro](https://t.me/Soushiyans_Pro) در تلگرام تماس بگیرید.

---

<div align="center">
  <p>طراحی و توسعه با عشق توسط <b>سوشیانس منصوری</b></p>
  <p><i>© 2026 LazyNoto Framework - MIT License</i></p>
</div>
