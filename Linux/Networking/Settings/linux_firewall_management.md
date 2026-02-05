# Настройка файрвола в Linux: iptables и nftables

## Определения

В основе фильтрации трафика в Linux лежит фреймворк **Netfilter**. Для управления им используются специальные утилиты. Основные концепции (Stateful Firewall, таблицы, цепочки) подробно описаны в заметке: **[Концепции сетевых файрволов](../../../Networking/Concepts/firewall_concepts.md)**.

*   **`iptables`** — это классическая утилита для управления правилами Netfilter.
*   **`nftables`** — это современная подсистема, заменяющая `iptables`, с более производительным и гибким синтаксисом.

## Базовые концепции

### 1. Инструменты управления
*   **Низкоуровневые (полный контроль):**
    *   `iptables`: Традиционная утилита. В современных системах часто является слоем совместимости над `nftables`.
    *   `nft`: Современная единая утилита для `nftables`.
*   **Высокоуровневые (упрощенный интерфейс):**
    *   `ufw` (Uncomplicated Firewall): Утилита по умолчанию в Ubuntu.
    *   `firewalld`: Динамический менеджер файрвола по умолчанию в RHEL-based дистрибутивах.

### 2. Архитектура `iptables`
-   **Правила (Rules):** Состоят из критериев (условий) и действия. Пакет сравнивается с правилами в цепочке по порядку. Как только совпадение найдено, выполняется действие, и обработка в этой цепочке прекращается.
-   **Действия (Targets):**
    -   `ACCEPT`: Разрешить пакет.
    -   `DROP`: Молча отбросить пакет. Отправитель не получает ответа.
    -   `REJECT`: Отклонить пакет с сообщением об ошибке (например, `icmp port-unreachable`).
    -   `LOG`: Записать информацию о пакете в системный лог. Обработка продолжается со следующего правила.

-   **Политика по умолчанию (Default Policy):** Действие, которое применяется, если пакет не совпал ни с одним правилом. Для безопасности рекомендуется `DROP`.

## Практические сценарии

### 1. Настройка `iptables` для веб-сервера

**Золотое правило:** сначала добавлять разрешающие (`ACCEPT`) правила для необходимого трафика, и только в конце устанавливать запрещающую (`DROP`) политику по умолчанию.

1.  **Разрешить установленные соединения (Stateful Firewall).** Это самое важное правило, оно позволяет пропускать ответный трафик.
    ```bash
    sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    ```
2.  **Разрешить трафик на loopback-интерфейсе:**
    ```bash
    sudo iptables -A INPUT -i lo -j ACCEPT
    ```
3.  **Разрешить необходимые новые входящие соединения:**
    ```bash
    # SSH (порт 22) - добавьте это правило первым, чтобы не потерять доступ!
    sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
    # HTTP (порт 80) и HTTPS (порт 443)
    sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
    ```
4.  **Разрешить ICMP (ping) для диагностики:**
    ```bash
    sudo iptables -A INPUT -p icmp --icmp-type 8 -j ACCEPT
    ```
5.  **Установить политику по умолчанию в `DROP`:**
    ```bash
    sudo iptables -P INPUT DROP
    sudo iptables -P FORWARD DROP
    sudo iptables -P OUTPUT ACCEPT # Для исходящего трафика обычно оставляют ACCEPT
    ```

### 2. Динамический бан брутфорса SSH с `nftables`

`nftables` позволяет создавать более сложные и производительные правила. Этот пример реализует защиту от брутфорса без `fail2ban`.

1.  **Создание таблицы, набора и цепочки:**
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
2.  **Применение и сохранение правил `nftables`:**
    ```bash
    # Сохранить текущие правила
    sudo nft list ruleset > /etc/nftables.conf
    # Включить сервис для автоматической загрузки при старте
    sudo systemctl enable --now nftables
    ```

## Дополнительная информация

### 1. Сохранение правил `iptables`

Правила `iptables` не сохраняются после перезагрузки по умолчанию.

-   **Debian/Ubuntu:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y iptables-persistent
    # Для сохранения измененных правил:
    sudo netfilter-persistent save
    ```

-   **RHEL/CentOS:**
    ```bash
    sudo yum install -y iptables-services
    sudo systemctl enable --now iptables
    # Для сохранения правил:
    sudo service iptables save
    ```

### 2. Взаимодействие `iptables` и Docker

Docker активно управляет `iptables` для обеспечения сетевой изоляции и проброса портов, добавляя собственные правила в цепочки `DOCKER` и `FORWARD`. Это создает несколько распространенных проблем:

1.  **Конфликт с политикой `FORWARD DROP`**: Если вы вручную устанавливаете политику по умолчанию для цепочки `FORWARD` в `DROP`, Docker не сможет доставить трафик в контейнеры.
    *   **Решение:** Вместо изменения глобальной политики, добавляйте свои правила в специальную цепочку `DOCKER-USER`. Docker обрабатывает правила из этой цепочки *перед* своими автоматическими правилами, что позволяет безопасно переопределять доступ к контейнерам.

2.  **Конфликт `iptables-legacy` и `iptables-nft`**: В современных дистрибутивах `iptables` является слоем совместимости над `nftables`. Если Docker пытается использовать `legacy`-синтаксис, а другая служба (например, `firewalld`) управляет `nftables` напрямую, правила Docker могут "затираться" или не работать.
    *   **Решение:** Явно переключить Docker и систему на использование `iptables-legacy`.

Подробный разбор этих проблем и примеры их решения находятся в отдельной заметке: **[Решение проблем: Docker и `iptables`](../../../Docker/Docker_network/troubleshooting/iptables_integration.md)**.

Ниже приведен пример добавления правил в `DOCKER-USER`:
```bash
# Пример: разрешить доступ к порту 8080 контейнера только с IP 1.2.3.4
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -s 1.2.3.4 -j ACCEPT
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -j DROP
```

### 3. `DROP` vs `REJECT`

-   `DROP`: Пакеты молча отбрасываются. Предпочтительный способ для внешней сети, так как не раскрывает информацию о хосте и замедляет сканирование портов.
-   `REJECT`: Отправителю отправляется ICMP-сообщение (`connection refused`). Может быть полезно для отладки во внутренних, доверенных сетях.

### 4. Полезные команды `iptables`
```bash
# Просмотр правил с номерами строк и счетчиками
sudo iptables -nvL --line-numbers

# Вставить правило на первую позицию в цепочке INPUT
sudo iptables -I INPUT 1 -s 1.2.3.4 -j DROP

# Удаление правила по номеру строки
sudo iptables -D INPUT 1

# Сброс всех правил и счетчиков (ОПАСНО!)
sudo iptables -F
sudo iptables -X
```