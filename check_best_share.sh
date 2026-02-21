#!/bin/sh
# Load environment variables
set -a
. /mnt/c/Users/YoungWolf/Documents/.env
set +a


# Kill script if it hangs longer than 20 seconds
( sleep 20 && kill $$ ) &

# -------- AUTH --------
USER="$ASIC_USER"
PASS="$ASIC_PASS"

# -------- MINERS --------
ASIC_IPS=(
  "192.168.1.199"  # S19k Pro
  "192.168.1.205"  # S21
)

HOSTNAMES=(
  "S19k Pro"
  "S21"
)

FIRMWARES=(
  "stock"
  "stock"
)

# -------- STATE FILES --------
LAST_FILES=(
  "C:/Users/YoungWolf/Documents/last_best_share_1.txt"
  "C:/Users/YoungWolf/Documents/last_best_share_2.txt"
)

# -------- TELEGRAM --------
TOKEN="$TELEGRAM_TOKEN"
CHAT_ID="$TELEGRAM_CHAT_ID"
# -------- INIT STATE FILES --------
for i in "${!LAST_FILES[@]}"; do
  [ ! -f "${LAST_FILES[$i]}" ] && echo 0 > "${LAST_FILES[$i]}"
done

# -------- MAIN LOOP --------
for i in "${!ASIC_IPS[@]}"; do
  ASIC_IP="${ASIC_IPS[$i]}"
  HOSTNAME="${HOSTNAMES[$i]}"
  FIRMWARE="${FIRMWARES[$i]}"
  LAST_FILE="${LAST_FILES[$i]}"

  if [ "$FIRMWARE" = "stock" ]; then
    RESPONSE=$(curl -s --digest -u "$USER:$PASS" "http://$ASIC_IP/cgi-bin/summary.cgi")
    BEST_SHARE=$(echo "$RESPONSE" | jq -r '.SUMMARY[0].bestshare')
  else
    echo "Unsupported firmware: $FIRMWARE"
    continue
  fi

  if [ -z "$BEST_SHARE" ] || [ "$BEST_SHARE" = "null" ]; then
    echo "[$HOSTNAME] Failed to read best share"
    continue
  fi

  LAST=$(cat "$LAST_FILE")

  if [ "$BEST_SHARE" -gt "$LAST" ] 2>/dev/null; then
    echo "$BEST_SHARE" > "$LAST_FILE"
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    MESSAGE="⚠️🧠 *ASIC Best Share Update*
\`\`\`
🖥️  Miner     : $HOSTNAME
🧮  Best Share: $BEST_SHARE
📦  Previous  : $LAST
⏰  Time      : $TIMESTAMP
\`\`\`"

    DATA="chat_id=$CHAT_ID&text=$(echo "$MESSAGE" | sed \
      's/ /%20/g; s/`/%60/g; s/\"/%22/g; s/\n/%0A/g')&parse_mode=MarkdownV2"

    {
      printf "POST /bot$TOKEN/sendMessage HTTP/1.1\r\n"
      printf "Host: api.telegram.org\r\n"
      printf "Content-Type: application/x-www-form-urlencoded\r\n"
      printf "Content-Length: %d\r\n\r\n" "$(echo -n "$DATA" | wc -c)"
      printf "%s\r\n" "$DATA"
      printf "quit\r\n"
    } | openssl s_client -connect api.telegram.org:443 -quiet

    echo "[$HOSTNAME] New best share: $BEST_SHARE"
  else
    echo "[$HOSTNAME] No improvement (current: $BEST_SHARE)"
  fi
done

exit 0
