# XiaoYang trên MotionAI (`ai_web`)

## Admin

**Admin → tab Bots → Engine render**

- Engine A / Engine B — ghi `bots/motionai_vps_bot.activeRenderProvider`
- Đơn **processing** giữ engine cũ; **pending** mới theo lựa chọn

## Bot VPS `.env`

```env
XIAOYANG_API_KEYS=xy_key1,xy_key2,xy_key3
# Bot chia đơn mới: đủ credit (Fast/Turbo) + key ít đơn processing nhất
# Thêm key → append vào chuỗi trên → restart bot
XIAOYANG_DIRECT_WORKER_URL=https://xiaoyang-direct-media.traderfinn0312.workers.dev
XIAOYANG_OPTION_KEY=default
BOT_MIN_RENDER_SEC=300
```

Aidancing vẫn qua CDP (`BOT_MODE=api` + `BOT_CDP_URL`). XiaoYang luôn pure HTTP.

| Web | `modelId` | XiaoYang |
|-----|-----------|----------|
| Fast | `124` / `125` | `motion_v26` |
| Turbo | `117` | `motion_v30` |

## Chạy bot

```bash
cd ~/ai_web && source .env
python3 bot.py --name motionai_vps_bot --mode api
```
