# Настройка вторичного DNS-сервера (Slave)

### 5. Настройка вторичного (Slave) DNS-сервера

1. Установите `bind9` и `dnsutils` так же, как на первичном сервере.
2. В файле `/etc/bind/named.conf.local` укажите зону как `slave`:

    ```
    zone "test.example.com" {
        type slave;
        file "/var/lib/bind/test.example.com.zone"; // BIND будет хранить копию здесь
        masters { 172.16.0.5; }; // IP-адрес первичного сервера
    };
    ```

3. Перезагрузите BIND. Он автоматически попытается получить копию зоны с `master`-сервера.
