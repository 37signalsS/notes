# NAT — Практические сценарии

### Настройка NAT в firewalld (Linux Router)

1. **Включить IP Forwarding:**

    ```bash
    # Временно
    sudo sysctl -w net.ipv4.ip_forward=1

    # Постоянно
    echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-router.conf
    sudo sysctl -p /etc/sysctl.d/99-router.conf
    ```

2. **Настроить NAT (Masquerading) в firewalld:**

    ```bash
    # Проверить активные зоны
    firewall-cmd --get-active-zones

    # Перевести внешний интерфейс в зону external
    firewall-cmd --zone=external --change-interface=<внешний_интерфейс> --permanent

    # Или добавить masquerading в текущую зону
    firewall-cmd --add-masquerade --permanent

    # Применить
    firewall-cmd --reload
    firewall-cmd --query-masquerade
    ```

    Зона `external` в firewalld по умолчанию имеет `masquerade=yes`.

3. **Проверка:**

    ```bash
    # С хоста внутренней сети
    ping 8.8.8.8

    # На роутере
    firewall-cmd --list-all
    ```

### Port Forwarding (DNAT)

**Port Forwarding (проброс портов)** — частный случай Destination NAT: трафик с порта публичного IP перенаправляется на внутренний хост.

**Пример через firewalld:** Веб-сервер `192.168.1.10:80`, внешний порт `8080`:

```bash
firewall-cmd --permanent --zone=external --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=192.168.1.10
firewall-cmd --reload
```

**Пример на iptables:**

```bash
# FORWARD
iptables -A FORWARD -i eth0 -o eth1 -p tcp --dport 80 -d 192.168.1.10 -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT

# DNAT
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80
```

**Схема работы DNAT:**

```
[Клиент из Интернета]
       |
       | Запрос на 203.0.113.50:8080
       v
[Linux Router (DNAT)]
       |  -> Переписывает dst: 203.0.113.50:8080 → 192.168.1.10:80
       v
[Внутренний сервер 192.168.1.10:80]
```

### Проброс SSH через iptables (альтернатива SSH ProxyJump)

**Сценарий:** Доступ к серверу B (серый IP) через сервер A (белый IP). Работает на сетевом уровне, в отличие от [SSH ProxyJump](../../../Linux/Security/ssh/ssh_client_config.md).

**Схема:**

```
[Клиент] --(SSH:2222)--> [Сервер A: белый IP] --(SSH:22)--> [Сервер B: серый IP]
```

**Настройка на сервере A:**

1. **DNAT:**

   ```bash
   iptables -t nat -A PREROUTING -p tcp --dport 2222 -j DNAT --to-destination <IP_сервера_B>:22
   ```

2. **MASQUERADE:**

   ```bash
   iptables -t nat -A POSTROUTING -d <IP_сервера_B> -o eth0 -j MASQUERADE
   ```

3. **FORWARD:**

   ```bash
   iptables -A FORWARD -p tcp -d <IP_сервера_B> --dport 22 -j ACCEPT
   iptables -A FORWARD -p tcp -s <IP_сервера_B> -j ACCEPT
   ```

4. **IP-форвардинг:**

   ```bash
   sysctl -w net.ipv4.ip_forward=1
   ```

**Подключение:**

```bash
ssh user@сервер_A -p 2222 -i my_private_key
```

**Сравнение с SSH ProxyJump:**

| Характеристика | **iptables DNAT** | **SSH ProxyJump** |
| :--- | :--- | :--- |
| **Уровень** | Сетевой (L3) | Прикладной (L7, SSH) |
| **Требования к серверу A** | root / iptables | SSH-доступ |
| **Безопасность** | Ниже (открытый порт) | Выше (шифрование, аутентификация) |
| **Производительность** | Выше | Ниже (SSH-инкапсуляция) |
| **Когда использовать** | Постоянный доступ, высокая нагрузка | Временный доступ, безопасность |

> **Рекомендация:** Временный доступ — [SSH ProxyJump](../../../Linux/Security/ssh/ssh_client_config.md). Постоянный — iptables DNAT.

**Схема работы NAT:**

```
[Внутренняя сеть] → [Linux Router (NAT)] → [Интернет]
     10.0.1.x              203.0.113.50 (публичный IP)
                  |
                  +-- SNAT: 10.0.1.x → 203.0.113.50
                  +-- DNAT: 203.0.113.50 → 10.0.1.x (ответы)
```

## Связанные документы

- **[Теория NAT](./overview.md)** — определения, виды, SNAT vs Masquerade
- **[Специальные IP-адреса](../../Protocols/IP_addressing/special_addresses.md)** — RFC 1918, Carrier-Grade NAT (RFC 6598)
- **[Firewalld — NAT](../../../Linux/Networking/Settings/tools/firewalld.md)** — команды firewalld
- **[nftables — NAT](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md)** — NAT в nftables
- **[Docker Network — iptables](../../../Docker/Docker_network/docker_network.md)** — NAT в Docker
