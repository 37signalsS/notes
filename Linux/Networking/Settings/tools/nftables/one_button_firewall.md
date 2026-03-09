# nftables: паттерн OneButtonFirewall

## Концепция

Файрвол, не требующий конфигурирования. Работает по принципу "IP-диода".

## Принцип работы

1. Внутренний сегмент (защищаемый) подключается к одним портам
2. Внешний сегмент (от которого защищаем) — к другим
3. Правила пропускают трафик только в одном направлении

## Правила фильтрации

- Запрещён транзит из внешнего сегмента во внутренний, кроме established/related
- Разрешён весь трафик из внутреннего во внешний
- Разрешён широковещательный трафик (для совместимости с Windows)
- Исключение: UDP 68 для DHCP (костыль для Linux-клиентов)

## Конфигурация

```bash
#!/usr/sbin/nft -f

flush ruleset

table bridge firewall {
    chain fw_forward {
        type filter hook forward priority filter; policy drop;

        # Разрешить весь трафик между внутренними портами
        # и трафик от внутренних портов к внешнему
        iifname != "external" accept

        # Разрешить IPv4 трафик по уже установленным соединениям
        ether type ip ct state established,related accept

        # Разрешить весь IPv4 трафик с широковещательными MAC-адресами
        ether type ip ether daddr ff:ff:ff:ff:ff:ff accept

        # Исключение для DHCP (UDP 68)
        # Нужно для получения адреса Linux-клиентами во внутреннем сегменте
        udp dport 68 accept
    }
}
```

## Конфигурация интерфейсов

```bash
# /etc/network/interfaces
auto lo
iface lo inet loopback

iface external inet manual
iface ens36 inet manual
iface ens37 inet manual
iface ens38 inet manual

auto br0
iface br0 inet manual
bridge_ports external ens36 ens37 ens38
```

## Преимущества

- Не требует настройки правил
- Автоматически адаптируется при изменении топологии
- Подходит для защиты периметра без глубокой сегментации

## Недостатки

- Нет детального контроля трафика
- Широковещательный трафик разрешён (риск broadcast storm)
- Не подходит для сложных политик безопасности
