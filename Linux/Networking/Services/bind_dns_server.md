# Настройка DNS-сервера BIND

## Определения

*   **DNS (Domain Name System)** — это иерархическая, распределенная система для преобразования доменных имен, понятных человеку, в IP-адреса и наоборот.
*   **BIND (Berkeley Internet Name Domain)** — это наиболее распространенное и широко используемое программное обеспечение для реализации DNS-сервера в Интернете.

## Базовые концепции

BIND реализует полную спецификацию протокола DNS и может выполнять несколько ролей:

*   **Авторитативный DNS-сервер**: Хранит официальную информацию о доменной зоне и отвечает на запросы о ней.
*   **Кэширующий (рекурсивный) DNS-сервер**: Принимает запросы от клиентов, находит ответы, опрашивая другие DNS-серверы в иерархии, и кэширует их для ускорения последующих запросов.
*   **Первичный (Master) и Вторичный (Slave) сервер**: Вторичный сервер автоматически копирует данные (трансфер зоны) с первичного, обеспечивая отказоустойчивость и распределение нагрузки.

## Практические сценарии

### 1. Установка BIND

Установка пакета `bind9` и утилит для диагностики DNS:
```bash
sudo apt-get update
sudo apt-get install -y bind9 dnsutils
sudo systemctl enable --now bind9
```

### 2. Базовая конфигурация (`/etc/bind/named.conf.options`)

Этот файл содержит общие настройки сервера.

```
options {
    directory "/var/cache/bind";
    
    // Для безопасности, если сервер не должен обслуживать внешних клиентов.
    // Если нужен рекурсивный сервер, установите 'yes' и настройте 'allow-recursion'.
    recursion no; 
    
    // Указываем, на каких IP-адресах сервер будет принимать запросы.
    listen-on { 172.16.0.5; 127.0.0.1; };
    
    // Серверы, на которые будут перенаправляться запросы, если наш сервер не знает ответа.
    // Используется, когда recursion=yes.
    forwarders {
        8.8.8.8;
        1.1.1.1;
    };

    dnssec-validation auto;
    listen-on-v6 { any; };
};
```
**Проверка синтаксиса:**
```bash
sudo named-checkconf
```

### 3. Настройка первичного (Master) DNS-сервера

#### 3.1. Описание зоны

Сначала в файле `/etc/bind/named.conf.local` объявляется новая зона.

```
zone "test.example.com" {
    type master;
    file "/etc/bind/zones/test.example.com.zone"; // Путь к файлу зоны
    allow-transfer { 172.16.0.6; }; // IP-адрес вторичного сервера
};
```

#### 3.2. Создание файла зоны

Создадим директорию и сам файл зоны:
```bash
sudo mkdir /etc/bind/zones
sudo touch /etc/bind/zones/test.example.com.zone
```

Содержимое файла зоны (`/etc/bind/zones/test.example.com.zone`):
```
$TTL 3600
@ IN SOA ns1.test.example.com. admin.test.example.com. (
    1          ; Серийный номер (увеличивать при каждом изменении!)
    3h         ; Refresh (частота проверки обновлений вторичным сервером)
    1h         ; Retry (интервал повторной попытки при неудаче)
    1w         ; Expire (время, через которое данные на вторичном сервере устареют)
    1h         ; Negative Cache TTL (время кэширования отрицательных ответов)
)

; NS-записи (указывают на DNS-серверы для этой зоны)
@ IN NS ns1.test.example.com.
@ IN NS ns2.test.example.com.

; A-записи (сопоставляют имена с IPv4-адресами)
@   IN A 172.16.101.3
ns1 IN A 172.16.0.5
ns2 IN A 172.16.0.6
```

#### 3.3. Проверка и применение

```bash
# Проверка синтаксиса файла зоны
sudo named-checkzone test.example.com /etc/bind/zones/test.example.com.zone

# Перезагрузка BIND для применения изменений
sudo systemctl restart bind9
```

### 4. Настройка вторичного (Slave) DNS-сервера

1.  Установите `bind9` и `dnsutils` так же, как на первичном сервере.
2.  В файле `/etc/bind/named.conf.local` укажите зону как `slave`:
    ```
    zone "test.example.com" {
        type slave;
        file "/var/lib/bind/test.example.com.zone"; // BIND будет хранить копию здесь
        masters { 172.16.0.5; }; // IP-адрес первичного сервера
    };
    ```
3.  Перезагрузите BIND. Он автоматически попытается получить копию зоны с `master`-сервера.

### 5. Настройка обратной зоны (Reverse Zone)

Обратная зона используется для определения имени хоста по его IP-адресу (PTR-записи).

#### 5.1. Описание и создание файла зоны

В `/etc/bind/named.conf.local` на первичном сервере:
```
zone "16.172.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/rev.16.172.in-addr.arpa";
    allow-transfer { 172.16.0.6; };
};
```
Файл `/etc/bind/zones/rev.16.172.in-addr.arpa`:
```
$TTL 3600
@ IN SOA ns1.test.example.com. admin.test.example.com. (
    1
    3h
    1h
    1w
    1h )
IN NS ns1.test.example.com.
IN NS ns2.test.example.com.

; PTR-записи (последние два октета IP-адреса в обратном порядке)
5.0     IN PTR ns1.test.example.com.
6.0     IN PTR ns2.test.example.com.
101.3   IN PTR host.test.example.com.
```
На вторичном сервере настройка аналогична, только `type slave`.

## Расширенные детали

### 1. Использование представлений (Views)

Представления (views) позволяют отдавать разные ответы на DNS-запросы в зависимости от того, из какой сети пришел запрос. Это полезно для разделения внутреннего и внешнего DNS.

В файле `/etc/bind/named.conf` настраиваем представления:
```
// Определяем ACL (Access Control List) для внутренней сети
acl "internal-net" { 172.16.0.0/16; 127.0.0.1; };

// Представление для внутренних клиентов
view "internal" {
    match-clients { internal-net; };
    recursion yes; // Разрешаем рекурсию для своих

    // Подключаем внутренние зоны
    include "/etc/bind/named.conf.local"; 
};

// Представление для всех остальных (внешних)
view "external" {
    match-clients { any; };
    recursion no; // Запрещаем рекурсию для чужих

    // Здесь можно подключить файл с публичными зонами
    // zone "public-example.com" { ... };
};
```

### 2. Логирование

Для отладки можно настроить детальное логирование. Создайте директорию для логов, доступную для BIND:
```bash
sudo mkdir /var/log/named
sudo chown bind:bind /var/log/named
# Настройте AppArmor, если он используется
# sudo nano /etc/apparmor.d/local/usr.sbin.named
# ... и добавьте: /var/log/named/** rw,
```

Подключите логирование в `/etc/bind/named.conf`:
```
logging {
    channel query.log {
        file "/var/log/named/query.log" versions 5 size 10m;
        severity info;
        print-time yes;
    };
    category queries { query.log; };
};
```
После настройки перезагрузите BIND.
