# Общие вопросы файрволов Linux

## Определения

Файл содержит общие вопросы настройки файрволов, не специфичные для конкретного инструмента (iptables/nftables/firewalld).

См. также:

- **[Концепции сетевых файрволов](../../../Networking/Concepts/firewall_concepts.md)** — теоретические основы (Netfilter, Stateful/Stateless)
- **[Лучшие практики правил](../../../Networking/Concepts/firewall_rules_best_practices.md)** — принципы проектирования правил
- **[iptables основы](./iptables_basics.md)** — синтаксис и команды iptables

---

## Basic Concepts

### Сохранение правил между перезагрузками

Правила файрволов не сохраняются после перезагрузки по умолчанию — требуется явное сохранение.

| Дистрибутив | Инструмент | Команда сохранения |
| :--- | :--- | :--- |
| **Debian/Ubuntu** | `iptables-persistent` | `sudo netfilter-persistent save` |
| **RHEL/CentOS 7+** | `iptables-services` | `sudo service iptables save` |
| **Современные (nftables)** | `nft` | `sudo nft list ruleset > /etc/nftables.conf` |

**Debian/Ubuntu:**

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

## Practical Scenarios

### Взаимодействие Docker и файрвола

Docker активно управляет `iptables` для сетевой изоляции контейнеров, добавляя правила в цепочки `DOCKER` и `FORWARD`.

**Типичные проблемы:**

1. **Конфликт с политикой `FORWARD DROP`**
   - **Проблема:** При политике `FORWARD DROP` трафик к контейнерам блокируется.
   - **Решение:** Добавлять правила в цепочку `DOCKER-USER` (обрабатывается до правил Docker).
   - **Подробности:** [Интеграция Docker с iptables](../../../Docker/Docker_network/troubleshooting/iptables_integration.md)

   ```bash
   # Разрешить доступ к порту 8080 контейнера только с IP 1.2.3.4
   sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -s 1.2.3.4 -j ACCEPT
   sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -j DROP
   ```

2. **Конфликт `iptables-legacy` и `iptables-nft`**
   - **Проблема:** В системах с `nftables` (через `firewalld`) правила Docker могут "затираться".
   - **Решение:** Переключить Docker на `iptables-legacy`.
   - **Подробности:** [Интеграция Docker с iptables](../../../Docker/Docker_network/troubleshooting/iptables_integration.md)

---

## Additional Information

### Сравнение `DROP` и `REJECT`

| Параметр | `DROP` | `REJECT` |
| :--- | :--- | :--- |
| **Поведение** | Пакеты молча отбрасываются | Отправляется ICMP-сообщение об ошибке |
| **Использование** | Внешние сети, интернет | Внутренние доверенные сети |
| **Безопасность** | Скрывает наличие хоста, замедляет сканирование | Раскрывает информацию о хосте |
| **Отладка** | Затруднена | Упрощена (видно "connection refused") |

**Рекомендация:** Используйте `DROP` для внешних интерфейсов и `REJECT` для внутренних сетей.

### Ссылки по теме

- **[iptables основы](./iptables_basics.md)** — полезные команды iptables
- **[nftables](./nftables.md)** — сохранение правил nftables
- **[firewalld](./firewalld.md)** — управление зонами и сервисами
