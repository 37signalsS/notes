# GRE с IPsec: защищённое туннелирование

## Обзор

Комбинация GRE и IPsec обеспечивает защищённый туннель: GRE отвечает за инкапсуляцию любых протоколов, IPsec — за шифрование и аутентификацию.

---

## Два подхода

### 1. GRE over IPsec (рекомендуется)

GRE-пакет инкапсулируется в IPsec ESP.

**Схема:**

```
[IP-пакет] → [GRE] → [IPsec ESP] → [Внешний IP]
```

**Преимущества:**

- IPsec защищает весь GRE-трафик (протокол 47)
- Меньший overhead по сравнению с IPsec over GRE
- Стандартный подход для site-to-site VPN

**Пример (strongSwan):**

```bash
# GRE-туннель
ip link add gre_sec type gre remote 203.0.113.2 local 198.51.100.1
ip link set gre_sec up
ip address add 10.0.0.1/30 dev gre_sec

# IPsec защищает протокол 47 (GRE)
# conn gre-tunnel in /etc/ipsec.conf:
# left=198.51.100.1, right=203.0.113.2
# leftprotoport=47, rightprotoport=47
```

### 2. IPsec over GRE

IPsec-пакет инкапсулируется в GRE.

**Схема:**

```
[IP-пакет] → [IPsec ESP] → [GRE] → [Внешний IP]
```

**Недостатки:**

- Дополнительный GRE-заголовок увеличивает overhead
- Уменьшает объём полезных данных в одном кадре
- Менее эффективен для производительности

**Применение:** Специфические сценарии с legacy-оборудованием.

---

## Сравнение подходов

| Параметр | GRE over IPsec | IPsec over GRE |
|----------|----------------|----------------|
| **Overhead** | ~24 байта (GRE) + ~56-73 байта (IPsec) | ~56-73 байта (IPsec) + ~24 байта (GRE) |
| **Эффективный MTU** | ~1400-1420 байт | ~1380-1400 байт |
| **Производительность** | Выше | Ниже |
| **Рекомендация** | **Да** (стандарт) | Нет (legacy) |

---

## Связанные документы

- **[GRE: архитектура](./gre_architecture.md)** — формат заголовка, версии GRE
- **[GRE: практические сценарии](./gre_practical_scenarios.md)** — настройка point-to-point, mGRE, GRETAP
- **[IPSec](./ipsec.md)** — режимы инкапсуляции, ESP/AH
- **[Troubleshooting GRE](./gre_troubleshooting.md)** — диагностика проблем
