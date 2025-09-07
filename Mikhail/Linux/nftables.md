# nftables без fail2ban: динамический бан брутфорса SSH (IPv4/IPv6)

**Задача:** быстро отстреливать источники, брутфорсящие SSH, без демонов и лог-парсеров. Решение - динамический `set` с таймаутом + правило, которое само добавляет нарушителя.

## 1. Создание таблицы, набора и цепочки

```bash
sudo nft -f - <<'EOF'
table inet fw {
  set ssh_bad {
    type inet_addr
    flags timeout
    timeout 1h      # дефолт для элементов
  }

  chain input {
    type filter hook input priority 0; policy accept;

    iif lo accept
    ct state established,related accept

    # уже занесённых — вон:
    ip saddr @ssh_bad drop

    # детект частых новых соединений на 22/tcp и бан + дроп:
    tcp dport 22 ct state new limit rate over 10/minute \
      add @ssh_bad { ip saddr timeout 2h } counter drop
  }
}
EOF
```

## 2. Ручное управление бан-листом

Админ-бан/разбан:
```bash
# Добавить IP в бан-лист с таймаутом 24 часа и комментарием
sudo nft add element inet fw ssh_bad { 203.0.113.5 timeout 24h comment "manual" }

# Удалить IP из бан-листа
sudo nft delete element inet fw ssh_bad { 203.0.113.5 }
```

## 3. Наблюдение за изменениями

Для отладки и мониторинга можно использовать:
```bash
sudo nft monitor set
```

## 4. Персистентность (Debian/Ubuntu/RHEL/Alma)

Сохранение правил после перезагрузки:
```bash
# Сохранить текущие правила в файл
sudo nft list ruleset > /etc/nftables.conf

# Проверить синтаксис и атомарно загрузить правила из файла
sudo nft -c -f /etc/nftables.conf && sudo nft -f /etc/nftables.conf

# Включить и запустить сервис
sudo systemctl enable --now nftables
```

**Совет:** вынеси блок в `/etc/nftables.d/ssh-ban.nft` и подключи его через `include` в основном файле `/etc/nftables.conf`.

---

### Зачем и когда это нужно

-   **Базовая защита:** Эффективная защита от простого брутфорса без установки и настройки сторонних сервисов вроде `fail2ban`.
-   **Легковесность:** Подходит для edge-устройств, виртуальных машин или хостов контейнеризации, где не нужен полный функционал `fail2ban`.
-   **Универсальность:** Работает в `family inet`, что означает единую логику и для IPv4, и для IPv6 адресов.

### Трюки и лучшие практики

-   `limit rate over` срабатывает только при **превышении** порога, поэтому обычные пользователи, подключающиеся по SSH, не пострадают.
-   Не используйте `flush table inet fw` в бою: это обнулит текущие динамические баны. Для обновления правил используйте точечные команды (`nft delete rule ...`, `nft add rule ...`) или всегда проверяйте синтаксис конфига (`nft -c -f ...`) перед его полной перезагрузкой.
-   Для нестандартных SSH-портов измените `tcp dport 22` на ваш порт.
```