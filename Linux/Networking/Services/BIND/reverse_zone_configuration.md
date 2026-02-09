# Настройка обратной зоны (Reverse Zone)

### 6. Настройка обратной зоны (Reverse Zone)

Обратная зона используется для определения имени хоста по его IP-адресу с помощью **[PTR-записей](../../../Networking/Protocols/dns.md#ptr--запись-указатель-обратные-зоны)**.

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
