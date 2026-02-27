# ip neighbour: Управление ARP-таблицей

Для доставки трафика в локальной сети система должна знать MAC-адрес устройства по его IP-адресу. Эту задачу решает протокол **[ARP (Address Resolution Protocol)](../../../../Networking/Protocols/arp.md)**. Команда `ip neighbour` управляет локальным ARP-кэшем.

* **Просмотреть ARP-таблицу (соответствие IP и MAC-адресов):**

    ```bash
    ip neighbour show
    ```

* **Очистить ARP-кэш для интерфейса:**

    ```bash
    sudo ip neighbour flush dev eth0
    ```
