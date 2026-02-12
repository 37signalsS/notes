# Использование heartbeat и механизмов failover

## Что такое heartbeat и как он влияет на отказоустойчивость

Heartbeat — это регулярный обмен сигналами между узлами кластера для подтверждения их живости. От его параметров зависит скорость и качество переключения:

*   Интервал отправки и временной порог потери: чем меньше интервалы, тем быстрее детектируется отказ, но выше риск ложных срабатываний при сетевых всплесках.
*   Транспорт и топология: unicast и multicast, уровень L2/L3, выделенная сеть для кластера снижает джиттер и потери.
*   Политики гистерезиса: fall/rise, backoff и dampening уменьшают «дребезг» при нестабильной сети.

Failover — автоматическое переназначение роли активного узла. На практике выбирают стратегию в зависимости от требований к RTO/RPO, модели данных (shared-nothing vs shared-storage) и способа публикации сервиса (виртуальный IP, L4/L7, DNS).

## Паттерны переключения: IP, кластерный менеджер, DNS

| Паттерн | Уровень | Инструменты | Плюсы | Минусы |
| :--- | :--- | :--- | :--- | :--- |
| IP failover (VRRP) | L3 (VIP) | Keepalived, VRRP | Просто, быстро | Только IP-слой, нужна проверка L7 |
| Кластер ресурсов | L4–L7 | Pacemaker + Corosync | Зависимости, правила, fencing | Сложнее, требует кворума |
| DNS failover | Глобальный | Health-check + короткий TTL | Геораспределение | TTL/кеш, не мгновенно |

Ключевые риски — split-brain и двойная активность. Для их предотвращения применяют кворум и fencing (STONITH) — гарантированное отключение/изолирование неисправного узла на уровне питания, гипервизора или хранилища.

## Keepalived/VRRP: быстрый IP-failover с проверкой сервиса

Вариант для сервисов, публикуемых через виртуальный IP. Рекомендуется проверять не только процесс, но и готовность к обслуживанию (L7 health-check).

Пример конфигурации с треком скрипта и подавлением агрессивного перебалансирования:

```keepalived
vrrp_script chk_http {
  script "/usr/local/bin/check_http.sh"
  interval 2
  fall 3
  rise 2
}

vrrp_instance VI_1 {
  state BACKUP
  interface eth0
  virtual_router_id 51
  priority 150
  advert_int 1
  virtual_ipaddress {
    10.0.0.100/24 dev eth0
  }
  track_script {
    chk_http
  }
  nopreempt
  preempt_delay 30
}
```

Пример простого health-check:

```sh
#!/bin/sh
curl -fsS http://127.0.0.1:80/health || exit 1
exit 0
```

Настройки nopreempt и preempt_delay помогают избежать «штормов возврата» при кратковременных сетевых проблемах.

## Pacemaker/Corosync: управление ресурсами и безопасный failover

Кластерный менеджер контролирует порядок запуска, колокацию ресурсов, мониторинг и fencing. Базовые команды для IP и сервиса, с включённым STONITH:

```bash
pcs cluster setup ha-cluster node1 node2
pcs cluster start --all
pcs property set stonith-enabled=true

pcs stonith create fence-ipmi fence_ipmilan pcmk_host_list="node1 node2" ipaddr="10.0.0.10" login="admin" passwd="secret" lanplus=1

pcs resource create vip IPaddr2 ip=10.0.0.100 cidr_netmask=24 op monitor interval=10s
pcs resource create web systemd:httpd op monitor interval=10s
pcs constraint colocation add web with vip INFINITY
pcs constraint order start vip then web
```

Рекомендации по настройке:

*   Выделяйте отдельную сеть для кворума и heartbeat; настраивайте token/consensus тайминги под реальные задержки.
*   Включайте fencing до ввода в эксплуатацию; тестируйте сценарии split-brain.
*   Подбирайте интервалы мониторинга и пороги fall/rise так, чтобы время переключения соответствовало SLA без избыточных ложных срабатываний.
