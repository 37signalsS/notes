# BIND: Дополнительная информация

## Дополнительная информация

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
