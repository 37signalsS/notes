Создаем папку, в ней создаем файл ansible.cfg и добавляем в него:

```ini
[defaults]
# Путь к файлу инвентаризации
inventory = inventory

# Путь к папке с ролями
roles_path = roles

# Отключение проверки SSH-ключей.

Необходимо, чтобы при первом запуске плейбука не подтверждать добавление хоста в список известных хостов на каждом сервере.

host_key_checking = False
```

## 2. Создание файла инвентаризации

Далее создайте файл `inventory`, в котором перечислите все необходимые для работы серверы.

**Пример с авторизацией по SSH-ключу:**

```ini
[rei]
195.2.73.85 ansible_user=root ansible_port=2414 ansible_ssh_private_key_file=~/.ssh/id_rsa
```

**Пример с разделением на группы и использованием паролей:**

```ini
[nodes]
192.168.0.139
192.168.0.140

[master]
192.168.0.138

[master:vars]
ansible_ssh_user=master
ansible_ssh_pass=master
ansible_become_pass=master # Пароль для sudo

[nodes:vars]
ansible_ssh_user=vagrant
ansible_ssh_pass=vagrant
ansible_become_pass=vagrant
```

## 3. Тестирование подключения

После создания файлов `ansible.cfg` и `inventory` можно протестировать подключение к серверам. Для этого используется модуль `ping`.

*   **К конкретной группе:** `ansible master -m ping`
*   **Ко всем нодам:** `ansible nodes -m ping`
*   **Ко всем серверам из файла инвентаризации:** `ansible all -m ping`

## 4. Выполнение команд

Модуль `shell` позволяет выполнять shell-команды на удаленных серверах.

**Пример:**

```bash
ansible all -m shell -a "ls -la /"
```

## 5. Пример плейбука

Ниже приведен пример плейбука, который копирует `authorized_keys` на все серверы и перезапускает службу SSHD при необходимости.

```yaml
- name: authorized_keys to servers
  hosts: all
  become: yes
  tasks:
    - name: Copy the updated authorized_keys file
      copy:
        src: /root/.ssh/authorized_keys
        dest: /root/.ssh/authorized_keys
        owner: "{{ ansible_user }}"
        group: "{{ ansible_user }}"
        mode: '0600'
      notify:
        - Restart SSHD if necessary

  handlers:
    - name: Restart SSHD if necessary
      service:
        name: sshd
        state: restarted
      when: sshd_service is defined and sshd_service.changed
```