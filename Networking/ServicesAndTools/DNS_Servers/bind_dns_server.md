# Настройка DNS-сервера BIND на Ubuntu

**DNS** — это система, в которой все доменные имена серверов находятся в определённой иерархии. BIND (Berkeley Internet Name Domain) — это наиболее распространенный DNS-сервер в Интернете.

## Установка BIND

Установка пакета `bind9` и утилит для работы с сетью:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install bind9 dnsutils
sudo service bind9 start
```

## Конфигурация

### Общие настройки (`/etc/bind/named.conf.options`)

```
options {
    directory "/var/cache/bind";
    
    // Запрещаем рекурсивные запросы, если сервер только для внутренних зон
    recursion no; 
    
    // Указываем, на каких интерфейсах слушать запросы
    listen-on { 172.16.0.0/16; 127.0.0.0/8; };
    
    // Серверы, на которые будут перенаправляться запросы, если наш сервер не знает ответа
    forwarders {
        172.16.0.1; // Например, шлюз
        8.8.8.8;    // Google DNS
    };

    dnssec-validation auto;
    auth-nxdomain no;
};
```
Проверка синтаксиса файла конфигурации:
```bash
sudo named-checkconf
```

### Настройка представлений (Views)

Представления позволяют отдавать разные ответы на DNS-запросы в зависимости от того, из какой сети пришел запрос (например, внутренняя или внешняя).

В файле `/etc/bind/named.conf` настраиваем представления:
```
// Подключаем общие опции
include "/etc/bind/named.conf.options";

// Определяем ACL (Access Control List) для локальной сети
acl "local" { 172.16.0.0/16; };

// Создаем представление для клиентов из локальной сети
view "local" {
    // Указываем, что это представление для клиентов из ACL "local"
    match-clients { local; };
    
    // Подключаем файл с описанием локальных зон
    include "/etc/bind/named.conf.local";
};
```

## Настройка первичного (Master) DNS-сервера

### 1. Создание файла зоны

Создадим директорию для файлов зон и сам файл:
```bash
sudo mkdir /etc/bind/master-zones
sudo touch /etc/bind/master-zones/test.example.com.local.zone
```

Содержимое файла зоны (`/etc/bind/master-zones/test.example.com.local.zone`):
```
$ttl 3600
$ORIGIN test.example.com.

@ IN SOA ns.test.example.com. abuse.test.example.com. (
    2022041201 ; Серийный номер (важно увеличивать при каждом изменении)
    10800      ; Refresh (время, через которое вторичный сервер будет проверять обновления)
    1200       ; Retry (время, через которое вторичный сервер повторит попытку, если первая не удалась)
    604800     ; Expire (время, через которое данные на вторичном сервере будут считаться устаревшими)
    3600       ; Negative Cache TTL (время кэширования отрицательных ответов)
)

; NS-записи (указывают на DNS-серверы для этой зоны)
@ IN NS ns.test.example.com.
@ IN NS ns2.test.example.com.

; A-записи (сопоставляют имена с IPv4-адресами)
@   IN A 172.16.101.3
ns  IN A 172.16.0.5
ns2 IN A 172.16.0.6
```
Проверка синтаксиса файла зоны:
```bash
sudo named-checkzone test.example.com. /etc/bind/master-zones/test.example.com.local.zone
```

### 2. Подключение зоны

В файле `/etc/bind/named.conf.local` прописываем зону:
```
zone "test.example.com." {
    type master;
    file "/etc/bind/master-zones/test.example.com.local.zone";
    // Разрешаем трансфер зоны только на вторичный DNS-сервер
    allow-transfer { 172.16.0.6; }; 
};
```

### 3. Перезагрузка BIND

```bash
sudo named-checkconf -z
sudo service bind9 restart
```

## Настройка вторичного (Slave) DNS-сервера

1.  Установите `bind9` и `dnsutils` так же, как на первичном сервере.
2.  Создайте директорию для файлов зон:
    ```bash
    sudo mkdir /etc/bind/slave
    sudo chmod g+w /etc/bind/slave
    ```
3.  В файле `/etc/bind/named.conf.local` укажите зону как `slave`:
    ```
    zone "test.example.com." {
        type slave;
        file "/etc/bind/slave/test.example.com.local.zone";
        masters { 172.16.0.5; }; // IP-адрес первичного сервера
    };
    ```
4.  Перезагрузите BIND:
    ```bash
    sudo named-checkconf -z
    sudo service bind9 restart
    ```
5.  Запустите трансфер зоны с первичного сервера:
    ```bash
    sudo rndc retransfer test.example.com
    ```

## Обратная зона (Reverse Zone)

Обратная зона используется для определения имени хоста по его IP-адресу (PTR-записи).

### 1. Создание файла обратной зоны

Файл `/etc/bind/master-zones/16.172.in-addr.arpa.zone`:
```
$TTL 3600
@ IN SOA ns.test.example.com. admin.test.example.com. (
    2022041202
    10800
    1200
    604800
    3600 )
IN NS ns.test.example.com.
IN NS ns2.test.example.com.

; PTR-записи (IP-адрес в обратном порядке)
3.101   IN PTR test.example.com.
5.0     IN PTR ns.test.example.com.
6.0     IN PTR ns2.test.example.com.
```

### 2. Подключение обратной зоны

В `/etc/bind/named.conf.local` на первичном сервере:
```
zone "16.172.in-addr.arpa." {
    type master;
    file "/etc/bind/master-zones/16.172.in-addr.arpa.zone";
    allow-transfer { 172.16.0.6; };
};
```
На вторичном сервере:
```
zone "16.172.in-addr.arpa." {
    type slave;
    file "/etc/bind/slave/16.172.in-addr.arpa.zone";
    masters { 172.16.0.5; };
};
```

## Логирование

Для отладки можно настроить логирование. Создайте файл `/etc/bind/log.conf`:
```
logging {
    channel bind.log {
        file "/var/lib/bind/bind.log" versions 10 size 20m;
        severity debug;
        print-category yes;
        print-severity yes;
        print-time yes;
    };
    category queries { bind.log; };
    category default { bind.log; };
    category config { bind.log; };
};
```
Подключите его в `/etc/bind/named.conf`:
```
include "/etc/bind/log.conf";
```
И перезагрузите BIND.
