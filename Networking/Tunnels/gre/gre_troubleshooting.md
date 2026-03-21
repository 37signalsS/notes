# GRE: диагностика и troubleshooting

## Проверка статуса

```bash
ip -d link show <gre_if>
ip address show <gre_if>
ip route get <remote_ip>
```

---

## Диагностика

### Проверка маршрута до remote

```bash
traceroute -n <remote_ip>
```

### Проверка инкапсуляции

```bash
tcpdump -i <phys_if> proto 47 -n
```

### Проверка MTU

```bash
ping -M do -s 1472 <remote_tunnel_ip>
```

---

## Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Туннель не поднимается | Нет маршрута до remote | Проверить маршрут до внешнего IP |
| Пакеты не проходят | MTU слишком большой | Установить MTU 1476 |
| Асимметричная маршрутизация | Разные пути туда/обратно | Настроить policy-based routing |
| Фрагментация | PMTU Discovery отключён | Включить `ip_no_pmtu_disc=0` |

---

## Связанные документы

- **[GRE: архитектура](./gre_architecture.md)** — формат заголовка, версии GRE
- **[GRE: практические сценарии](./gre_practical_scenarios.md)** — настройка point-to-point, mGRE, GRETAP
- **[GRE с IPsec](./gre_ipsec_integration.md)** — защищённая комбинация
- **[IPSec troubleshooting](../ipsec/ipsec_troubleshooting.md)** — диагностика IPsec
