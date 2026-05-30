# Общие вопросы файрволов Linux

## Определения

Файл содержит общие вопросы настройки файрволов, не специфичные для конкретного инструмента (iptables/nftables/firewalld).

**Важно:** В Debian 11+ и современных дистрибутивах по умолчанию используется **nftables**. Классический `iptables` может отсутствовать или быть слоем совместимости (`iptables-nft`).

См. также:

- **[Концепции сетевых файрволов](../../../../Networking/Concepts/firewall_concepts.md)** — теоретические основы (Netfilter, Stateful/Stateless)
- **[Лучшие практики правил](../../../../Networking/Concepts/firewall_rules_best_practices.md)** — принципы проектирования правил
- **[iptables основы](./iptables_basics.md)** — синтаксис и команды iptables
- **[nftables](../tools/nftables/practical_scenarios.md)** — современная подсистема (рекомендуется для Debian 11+)

---

## Основные концепции

### Сохранение правил между перезагрузками

Правила файрволов не сохраняются после перезагрузки по умолчанию — требуется явное сохранение.

| Дистрибутив | Инструмент | Команда сохранения | Примечание |
| :--- | :--- | :--- | :--- |
| **Debian 10/Ubuntu 18.04** | `iptables-persistent` | `sudo netfilter-persistent save` | Классический iptables |
| **Debian 11+/Ubuntu 22.04+** | `nftables` | `sudo nft list ruleset > /etc/nftables.conf` | **nftables по умолчанию** |
| **RHEL/CentOS 7+** | `iptables-services` | `sudo service iptables save` | |
| **RHEL/Fedora (новые)** | `nftables` / `firewalld` | `sudo nft list ruleset > /etc/nftables.conf` | |

**Debian 11+ (nftables):**

```bash
# Сохранение правил
sudo nft list ruleset > /etc/nftables.conf

# Включение автозагрузки
sudo systemctl enable --now nftables
```

**Подробнее:** **[nftables: современная подсистема фильтрации](../tools/nftables/practical_scenarios.md)** — архитектура, синтаксис, практические сценарии (fail2ban, сегментирование, тестирование).

**Debian/Ubuntu (классический iptables):**

```bash
sudo apt-get update && sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

**RHEL/CentOS:**

```bash
sudo yum install -y iptables-services
sudo systemctl enable --now iptables
sudo service iptables save
```

---

## Практические сценарии

### Взаимодействие Docker и файрвола

Docker активно управляет сетевым стеком через `iptables` для обеспечения изоляции и маршрутизации трафика контейнеров.

Подробные сценарии решения конфликтов (политика `FORWARD DROP`, использование `iptables-legacy` vs `iptables-nft`) и описание цепочки `DOCKER-USER` доступны в специализированном документе:

**[Интеграция Docker с iptables](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)**.

---

## Дополнительная информация

### Сравнение `DROP` и `REJECT`

| Параметр | `DROP` | `REJECT` |
| :--- | :--- | :--- |
| **Поведение** | Пакеты молча отбрасываются | Отправляется **ICMP (Internet Control Message Protocol)** сообщение об ошибке |
| **Использование** | Внешние сети, интернет | Внутренние доверенные сети |
| **Безопасность** | Скрывает наличие хоста, замедляет сканирование | Раскрывает информацию о хосте |
| **Отладка** | Затруднена | Упрощена (видно "connection refused") |

**Рекомендация:** Используйте `DROP` для внешних интерфейсов и `REJECT` для внутренних сетей.

### Ссылки по теме

- **[iptables основы](./iptables_basics.md)** — полезные команды iptables
- **[nftables](../tools/nftables/practical_scenarios.md)** — сохранение правил nftables
- **[firewalld](./firewalld.md)** — управление зонами и сервисами
- **[ufw](./ufw.md)** — упрощенный интерфейс для Ubuntu/Debian
