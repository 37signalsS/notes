# ip tunnel: Управление туннелями

`iproute2` позволяет создавать различные типы **[сетевых туннелей](../../../Networking/Tunnels/tunneling_overview.md)**, которые инкапсулируют пакеты одного протокола в другой.

* **Пример создания [GRE-туннеля](../../../Networking/Tunnels/gre.md):**

    ```bash
    # Создать туннель
    sudo ip tunnel add gre1 mode gre remote 203.0.113.2 local 198.51.100.1 ttl 255
    # Включить его
    sudo ip link set gre1 up
    # Назначить адрес
    sudo ip address add 10.0.0.1/30 dev gre1
    ```

    *Для создания туннелей также можно использовать более современный синтаксис `ip link add type <type> ...`.*
