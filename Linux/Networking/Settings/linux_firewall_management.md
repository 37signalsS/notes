# Настройка файрвола в Linux: iptables и nftables

## Определения

*   **Пакетный фильтр** — это механизм ядра операционной системы, который инспектирует сетевые пакеты и принимает решения (пропустить, заблокировать, изменить) на основе набора правил.
*   **Netfilter** — это фреймворк внутри ядра Linux, предоставляющий "хуки" (точки входа) для перехвата и обработки сетевых пакетов.
*   **`iptables`** — это классическая утилита командной строки для управления правилами Netfilter.
*   **`nftables`** — это современная подсистема, заменяющая `iptables`, с более производительным и гибким синтаксисом.

## Базовые концепции

### 1. Инструменты управления

Для настройки пакетного фильтра в Linux используются разные утилиты:
*   **Прямое управление (рекомендуется для полного контроля):**
    *   `iptables`, `ip6tables`: Традиционные утилиты. В современных системах часто являются слоем совместимости над `nftables`.
    *   `nft`: Современная единая утилита для `nftables`.
*   **Инструменты-надстройки (упрощенный интерфейс):**
    *   `ufw` (Uncomplicated Firewall): Утилита по умолчанию в Ubuntu.
    *   `firewalld`: Динамический менеджер файрвола по умолчанию в RHEL-based дистрибутивах.

### 2. Архитектура `iptables`

-   **Правила (Rules):** Состоят из критериев (условий) и действия (target). Пакет сравнивается с правилами в цепочке по порядку, сверху вниз. Как только совпадение найдено, выполняется указанное действие, и обработка пакета в этой цепочке прекращается.

-   **Действия (Targets):**
    -   `ACCEPT`: Разрешить прохождение пакета.
    -   `DROP`: Молча отбросить пакет. Отправитель не получает ответа.
    -   `REJECT`: Отклонить пакет с сообщением об ошибке (например, `icmp port-unreachable`).
    -   `LOG`: Записать информацию о пакете в системный лог. Обработка продолжается со следующего правила.

-   **Политика по умолчанию (Default Policy):** Действие, которое применяется, если пакет не совпал ни с одним правилом. Для безопасности рекомендуется `DROP`.

## Практические сценарии

### 1. Настройка `iptables` для веб-сервера

**Золотое правило:** сначала добавлять разрешающие (`ACCEPT`) правила, и только потом устанавливать запрещающую (`DROP`) политику.

#### Шаг 1: Диагностика и подготовка
```bash
# Просмотр текущих правил
sudo iptables -nvL --line-numbers

# Просмотр слушающих сокетов для выявления сервисов
sudo ss -ntulp
```

2.  **Разрешить установленные и связанные соединения (Stateful Firewall).** Это самое важное правило.
    ```bash
    # Для iptables < 1.8.7
    sudo iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    # Для iptables >= 1.8.7 (и nftables)
    sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    ```

3.  **Разрешить трафик на loopback-интерфейсе:**
    ```bash
    sudo iptables -A INPUT -i lo -j ACCEPT
    sudo iptables -A OUTPUT -o lo -j ACCEPT
    ```

4.  **Блокировать невалидные пакеты:**
    ```bash
    sudo iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
    ```

5.  **Разрешить необходимые новые соединения (SSH, HTTP, HTTPS):**
    ```bash
    # SSH (порт 22) - добавьте это правило первым, чтобы не потерять доступ!
    sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
    # HTTP (порт 80)
    sudo iptables -A INPUT -p tcp --dport 80 -m conntrack --ctstate NEW -j ACCEPT
    # HTTPS (порт 443)
    sudo iptables -A INPUT -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
    ```

6.  **Разрешить ICMP (ping):**
    ```bash
    sudo iptables -A INPUT -p icmp -j ACCEPT
    ```

7.  **Установить политику по умолчанию в `DROP` (финальный шаг):**
    ```bash
    sudo iptables -P INPUT DROP
    sudo iptables -P FORWARD DROP
    # Политику OUTPUT также можно установить в DROP для контроля исходящего трафика,
    # но это требует добавления разрешающих правил для DNS, NTP, обновлений и т.д.
    # sudo iptables -P OUTPUT DROP
    ```

#### Сохранение правил `iptables`

Правила `iptables` не сохраняются после перезагрузки.

-   **Debian/Ubuntu:** Используйте пакет `iptables-persistent`.
    ```bash
    sudo apt update && sudo apt install iptables-persistent
    # Правила сохраняются в /etc/iptables/rules.v4
    # Для сохранения измененных правил:
    sudo netfilter-persistent save
    ```
-   **RHEL/CentOS:** Используйте `iptables-services`.
    ```bash
    sudo yum install iptables-services
    sudo systemctl enable iptables
    sudo systemctl start iptables
    ```
    *Примечание:* Команда `sudo service iptables save` устарела, используйте `sudo systemctl start iptables` для запуска сервиса, который сохранит правила.

#### Взаимодействие `iptables` и Docker

Docker активно управляет `iptables`. Ключевой момент: трафик к контейнерам идет через цепочку **`FORWARD`**, а не `INPUT`.

-   **Проблема:** Если вы установили политику `sudo iptables -P FORWARD DROP`, доступ к опубликованным портам контейнеров будет заблокирован.
-   **Решение:** Docker создает специальную цепочку `DOCKER-USER`. Правила, добавленные в эту цепочку, выполняются *перед* автоматическими правилами Docker. Это рекомендуемое место для добавления собственных правил.
    ```bash
    # Пример: разрешить доступ к порту 8080 только с IP 1.2.3.4
    # -i enp0s3 - ваш внешний интерфейс
    sudo iptables -I DOCKER-USER -i enp0s3 -p tcp --dport 8080 -s 1.2.3.4 -j ACCEPT
    ```

## 3. `nftables`: Современная замена

В современных дистрибутивах Linux `iptables` является слоем совместимости поверх `nftables`.

### 2. Динамический бан брутфорса SSH с `nftables`

Этот пример показывает, как реализовать защиту от брутфорса без `fail2ban`.

1.  **Создание таблицы, набора и цепочки:**
    ```bash
    sudo nft -f - <<'EOF'
    # Очищаем все правила перед применением новых
    flush ruleset

    table inet fw {
      set ssh_bad {
        type inet_addr
        flags timeout
        timeout 1h      # Время бана по умолчанию для элементов
      }

      chain input {
        type filter hook input priority 0; policy accept;

        # Правило 1: Разрешить трафик на loopback
        iif lo accept

        # Правило 2: Разрешить установленные и связанные соединения
        ct state established,related accept

        # Правило 3: Бросать пакеты от уже забаненных адресов
        ip saddr @ssh_bad drop

        # Правило 4: Детектировать брутфорс, банить и бросать пакет
        # Если количество новых соединений на порт 22 превышает 10 в минуту...
        tcp dport 22 ct state new limit rate over 10/minute \
          add @ssh_bad { ip saddr timeout 2h } counter drop # ...добавить IP в набор с баном на 2 часа и отбросить пакет
      }
    }
    EOF
    ```

2.  **Ручное управление бан-листом:**
    ```bash
    # Забанить IP на 24 часа с комментарием
    sudo nft add element inet fw ssh_bad { 203.0.113.5 timeout 24h comment "manual" }

    # Разбанить IP
    sudo nft delete element inet fw ssh_bad { 203.0.113.5 }
    ```

3.  **Сохранение правил `nftables`:**
    ```bash
    # Сохранить текущие правила
    sudo nft list ruleset > /etc/nftables.conf

    # Включить и запустить сервис для автоматической загрузки при старте
    sudo systemctl enable --now nftables
    ```

## Расширенные детали

### 1. `DROP` vs `REJECT`

-   `DROP`: Пакеты молча отбрасываются. Предпочтительный способ, так как не раскрывает информацию о хосте и замедляет сканирование портов.
-   `REJECT`: Отправителю отправляется ICMP-сообщение (`connection refused`). Используется редко, в основном для отладки в доверенных сетях.

### 2. Взаимодействие `iptables` и Docker

Docker активно управляет `iptables`, добавляя правила в таблицу `nat` и цепочку `FORWARD`.
-   **Проблема:** Если вы установили политику `sudo iptables -P FORWARD DROP`, доступ к опубликованным портам контейнеров будет заблокирован.
-   **Решение:** Docker создает специальную цепочку `DOCKER-USER`. Правила, добавленные в эту цепочку, выполняются *перед* автоматическими правилами Docker. Это рекомендуемое место для добавления собственных правил.
    ```bash
    # Пример: разрешить доступ к порту 8080 только с IP 1.2.3.4
    sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -s 1.2.3.4 -j ACCEPT
    ```

### 3. Полезные команды `iptables`

-   **Просмотр правил в таблице `filter`:**
    ```bash
    # -n: не преобразовывать IP и порты в имена
    # -v: подробный вывод (счетчики пакетов и байт)
    # -L: список правил
    # --line-numbers: показать номера строк
    sudo iptables -nvL --line-numbers
    ```
-   **Вставка правила в определенную позицию:**
    ```bash
    # Вставить правило на первую позицию в цепочке INPUT
    sudo iptables -I INPUT 1 -s 1.2.3.4 -j DROP
    ```
-   **Удаление правила:**
    ```bash
    # По номеру строки
    sudo iptables -D INPUT 1
    # По спецификации правила
    sudo iptables -D INPUT -s 1.2.3.4 -j DROP
    ```

- **Сброс всех правил (ОПАСНО!):**
  ```bash
  sudo iptables -F
  ```
