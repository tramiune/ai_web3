# MotionAI Bot (web1) — Hướng dẫn VPS & xử lý lỗi

Bot tự động nạp đơn lên **aidancing.net** và trả kết quả về Firebase (project `motionai-studio-76be9`).

Chạy song song với **web2** trên cùng VPS — mỗi bot **Chrome + port + profile riêng**.

---

## Web1 vs Web2 (cùng VPS)

| | **Web1** (repo này) | **Web2** (`ai_web2`) |
|---|---|---|
| Firebase | `motionai-studio-76be9` | `wallpaper-6cbbe` |
| Repo VPS | `~/ai_web` | `~/ai_web2` |
| Bot name | `motionai_vps_bot` | `nhaycloud_vps_bot` |
| CDP port | **9222** | **9223** |
| Chrome profile | `~/.chrome-aidancing-motionai` | `~/.chrome-aidancing-wallpaper` |
| Profile Chrome | **Profile 4** (Finn Trader) | **Profile 14** (Lan Trần) |
| tmux Chrome | `chrome-motion` | `chrome` |
| tmux bot | `bot-motion` | `bot` |
| Aidancing account | traderfinn0312 / Google | lantran03122001 / Google |

---

## Thông số web1

| Mục | Giá trị |
|-----|---------|
| VPS | `hoang1432001@136.119.193.255` |
| GitHub | `github.com/tramiune/ai_web` |

---

## 1. Setup lần đầu trên VPS

### 1.1 Clone & cài package

```bash
ssh hoang1432001@136.119.193.255

cd ~
git clone https://github.com/tramiune/ai_web.git
cd ai_web
pip3 install -r requirements.txt
python3 -m playwright install-deps
```

*(Nếu VPS đã cài cho web2: bỏ qua `apt install` — dùng chung `xvfb`, `google-chrome`, `tmux`.)*

### 1.2 Copy `serviceAccountKey.json` (MotionAI Firebase)

```bash
# Trên Mac
scp ~/Documents/Tramiune/ai_web/serviceAccountKey.json hoang1432001@136.119.193.255:~/ai_web/
```

### 1.3 Copy Chrome profile từ Mac (Profile 4 — Finn Trader)

**Trên Mac** — thoát hết Chrome (Cmd+Q):

```bash
rm -rf ~/.chrome-aidancing-motionai
mkdir -p ~/.chrome-aidancing-motionai
cp "$HOME/Library/Application Support/Google/Chrome/Local State" ~/.chrome-aidancing-motionai/
cp -R "$HOME/Library/Application Support/Google/Chrome/Profile 4" ~/.chrome-aidancing-motionai/

tar czf ~/chrome-motionai.tar.gz -C ~/.chrome-aidancing-motionai .
scp ~/chrome-motionai.tar.gz hoang1432001@136.119.193.255:~/
```

**Trên VPS:**

```bash
rm -rf ~/.chrome-aidancing-motionai
mkdir -p ~/.chrome-aidancing-motionai
tar xzf ~/chrome-motionai.tar.gz -C ~/.chrome-aidancing-motionai
# Bỏ qua cảnh báo tar LIBARCHIVE.xattr — vô hại

rm -f ~/.chrome-aidancing-motionai/SingletonLock \
      ~/.chrome-aidancing-motionai/SingletonCookie \
      ~/.chrome-aidancing-motionai/SingletonSocket
```

---

## 2. Quy trình hàng ngày / sau reboot

```bash
ssh hoang1432001@136.119.193.255
```

### Một lệnh gộp (web1)

```bash
tmux kill-session -t chrome-motion 2>/dev/null; tmux kill-session -t bot-motion 2>/dev/null
tmux new-session -d -s chrome-motion "xvfb-run -a --server-args='-screen 0 1280x800x24' google-chrome --remote-debugging-port=9222 --remote-allow-origins='*' --user-data-dir=\$HOME/.chrome-aidancing-motionai --profile-directory='Profile 4' --no-first-run --no-default-browser-check --disable-gpu"
sleep 15
curl -s http://127.0.0.1:9222/json/version | head -2
curl -s http://127.0.0.1:9222/json/list | grep dashboard
tmux new-session -d -s bot-motion "cd ~/ai_web && export BOT_CDP_URL=http://127.0.0.1:9222 && python3 bot.py --name motionai_vps_bot --mode api"
tmux ls
```

### Admin

MotionAI Studio → **Admin → Bots** → bật `motionai_vps_bot`.

---

## 3. Login Aidancing (Google Auth)

Giống web2 — **SSH tunnel port 9222** (không phải 9223):

**Terminal Mac:**

```bash
ssh -L 9222:127.0.0.1:9222 hoang1432001@136.119.193.255
```

**Mac Chrome** → `chrome://inspect/#devices` → Configure `localhost:9222` → **inspect** tab aidancing → login Google (**Finn Trader**) → vào **Dashboard**.

**Kiểm tra VPS:**

```bash
curl -s http://127.0.0.1:9222/json/list | grep dashboard
```

---

## 4. Chạy cả web1 + web2 cùng lúc

Sau reboot, chạy **cả hai block** (web2 trước hoặc sau đều được):

```bash
# --- Web2 (Nhay Cloud) port 9223 ---
tmux new-session -d -s chrome "xvfb-run -a --server-args='-screen 0 1280x800x24' google-chrome --remote-debugging-port=9223 --remote-allow-origins='*' --user-data-dir=\$HOME/.chrome-aidancing-wallpaper --profile-directory='Profile 14' --no-first-run --no-default-browser-check --disable-gpu"
tmux new-session -d -s bot "cd ~/ai_web2 && export BOT_CDP_URL=http://127.0.0.1:9223 && python3 bot.py --name nhaycloud_vps_bot --mode api"

# --- Web1 (MotionAI) port 9222 ---
tmux new-session -d -s chrome-motion "xvfb-run -a --server-args='-screen 0 1280x800x24' google-chrome --remote-debugging-port=9222 --remote-allow-origins='*' --user-data-dir=\$HOME/.chrome-aidancing-motionai --profile-directory='Profile 4' --no-first-run --no-default-browser-check --disable-gpu"
tmux new-session -d -s bot-motion "cd ~/ai_web && export BOT_CDP_URL=http://127.0.0.1:9222 && python3 bot.py --name motionai_vps_bot --mode api"

sleep 15
tmux ls
curl -s http://127.0.0.1:9222/json/version | head -1
curl -s http://127.0.0.1:9223/json/version | head -1
```

Login inspect: tunnel **9222** cho web1, tunnel **9223** cho web2 (hai terminal Mac hoặc hai port forward).

---

## 5. Xem log

```bash
tmux capture-pane -t bot-motion -p | tail -20    # bot web1
tmux capture-pane -t chrome-motion -p | tail -10 # Chrome web1
tmux attach -t bot-motion   # thoát: Ctrl+B rồi D
```

Log thành công:

```
🆔 [API] Job mới: ...
✅ Đơn ... → processing
```

---

## 6. Cập nhật code

```bash
cd ~/ai_web && git pull
tmux send-keys -t bot-motion C-c Enter
sleep 2
tmux send-keys -t bot-motion 'cd ~/ai_web && export BOT_CDP_URL=http://127.0.0.1:9222 && python3 bot.py --name motionai_vps_bot --mode api' Enter
```

---

## 7. Xử lý lỗi

| Triệu chứng | Cách xử lý |
|-------------|------------|
| `401 đăng nhập lại` | Login Google qua inspect port **9222** (mục 3) |
| `curl 9222` rỗng | `sleep 15`; xem `tmux capture-pane -t chrome-motion` |
| Port conflict | Web1 = **9222**, web2 = **9223** — không trùng |
| Lỗi Aidancing hiện cho khách | Pull code mới — chỉ gửi **Telegram** `[MotionAI]` |
| Copy profile Mac vẫn 401 | Bình thường trên Linux — **bắt buộc login inspect** lần đầu |

Chi tiết web2: xem `ai_web2/README.md`.

---

## 8. Chạy local Mac (tùy chọn)

```bash
cd ~/Documents/Tramiune/ai_web
pip install -r requirements.txt

# Terminal 1 — Chrome port 9222
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir="$HOME/.chrome-aidancing-motionai" \
  --profile-directory="Profile 4"

# Terminal 2
export BOT_CDP_URL=http://127.0.0.1:9222
python3 bot.py --name motionai_local --mode api
```

---

## 9. File không commit Git

- `serviceAccountKey.json`
- `~/.chrome-aidancing-motionai/`
- `bot_chrome_profile/`
