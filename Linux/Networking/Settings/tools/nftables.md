# nftables: современная подсистема фильтрации

> [Назад к оглавлению](../linux_firewall_management.md)

## Определения

**nftables** — это современная подсистема Linux для фильтрации сетевого трафика, заменяющая `iptables`. Она использует фреймворк **Netfilter** и предоставляет более производительный и гибкий синтаксис.

## Базовые концепции

### Инструменты управления

* **Низкоуровневые (полный контроль):**
  * `nft`: Единая утилита для управления `nftables`.

## Практические сценарии

### Динамический бан брутфорса SSH с `nftables`

`nftables` позволяет создавать более сложные и производительные правила. Этот пример реализует защиту от брутфорса без `fail2ban`.

1. **Создание таблицы, набора и цепочки:**

    ```bash
    sudo nft -f - <<'EOF'
    flush ruleset

    table inet filter {
      set ssh_bruteforce {
        type ipv4_addr
        flags timeout
      }

      chain input {
        type filter hook input priority 0; policy accept;

        # Разрешить установленные и связанные соединения
        ct state established,related accept

        # Блокировать пакеты от уже забаненных адресов
        ip saddr @ssh_bruteforce drop

        # Детектировать брутфорс, банить и блокировать пакет
        # Если количество новых соединений на порт 22 превышает 5 за минуту...
        tcp dport 22 ct state new limit rate over 5/minute \
          add @ssh_bruteforce { ip saddr timeout 15m } drop
      }
    }
    EOF
    ```

2. **Применение и сохранение правил `nftables`:**

    ```bash
    # Сохранить текущие правила
    sudo nft list ruleset > /etc/nftables.conf
    # Включить сервис для автоматической загрузки при старте
    sudo systemctl enable --now nftables
    ```

---

## Дополнительная информация

См. также: **[Общие вопросы файрволов: сохранение правил, Docker, команды](firewall_common.md)**
