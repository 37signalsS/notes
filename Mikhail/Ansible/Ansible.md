---
sr-due: 2025-05-15
sr-interval: 3
sr-ease: 250
---

#review
Создаем папку, в ней создаем файл ansible.cfg и добавляем в него:

``` 
[defaults]
inventory = inventory

roles_path = roles

#Отключаем проверку ssh ключей(необходимо чтобы при запуске плейбука в первый раз не прожимать yes ssh-агенту на каждом сервере)
host_key_checking = False
```

Далее создаем файл inventory, где упоминаем все необходимые машины(коннект будет не сразу, необходимо на каждом серваке ответить yes ssh-агенту), если необходима авторизация по ssh ключу то используем: 

```
[rei]
195.2.73.85 ansible_user=root ansible_port=2414 ansible_ssh_private_key_file=~/.ssh/id_rsa
```

```
[nodes]
192.168.0.139
192.168.0.140

[master]
192.168.0.138

[master:vars]
ansible_ssh_user=master
ansible_ssh_pass=master
ansible_become_pass=master #Пароль для sudo

[nodes:vars]
ansible_ssh_user=vagrant
ansible_ssh_pass=vagrant
ansible_become_pass=vagrant
```

После составление инветаризации и главного конфиг файла можно протестировать подключение, например, к главному серверу - ansible master, к всем нодам - nodes, к всем серверам - all. 

Далее параметр -m который вызывает дефолтные модули ansible, например, модуль ping который проверяет можут ли ansible подключиться по учетным данным которыми он распологает.

Модуль shell -a "" может выполнить шелл команду

``` yaml
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














Зачем необходимо отключать проверку ssh ключей::необходимо чтобы при запуске плейбука в первый раз не прожимать yes ssh-агенту на каждом сервере

Как указать путь к инвентарному файлу в конфигурации Ansible::используйте параметр `inventory`, например: `inventory = inventory`

Где указывается путь к ролям в Ansible::в файле `ansible.cfg` используется параметр `roles_path`, например: `roles_path = roles`

Как добавить SSH-ключ для подключения к серверу в файле инвентаризации::используйте параметр `ansible_ssh_private_key_file`, например:  
`195.2.73.85 ansible_user=root ansible_port=2414 ansible_ssh_private_key_file=~/.ssh/id_rsa`

Как задать переменные для группы серверов в файле инвентаризации::используйте секцию `:vars` после имени группы.

Как протестировать подключение Ansible к группе серверов::используйте команду `ansible <группа> -m ping`, например:  `ansible master -m ping`

Как выполнить команду на удаленном сервере с помощью Ansible::используйте модуль `shell` с параметром `-a`, например:  `ansible all -m shell -a "ls -l"`

Как скопировать файл на удаленные серверы с помощью Ansible::используйте модуль `copy` в playbook.

Как перезапустить службу SSHD на удаленных серверах при необходимости::используйте обработчик (handler) в playbook, например:  

Как указать пользователя и пароль для подключения к серверам в файле инвентаризации::используйте параметры `ansible_ssh_user` и `ansible_ssh_pass`.

Какие группы серверов определены в примере файла инвентаризации::определены группы `[rei]`, `[nodes]`, `[master]`

Как указать порт для подключения к серверу в файле инвентаризации::используйте параметр `ansible_port`, например:  `195.2.73.85 ansible_user=root ansible_port=2414`

Что делает параметр `become` в playbook::параметр `become` позволяет выполнять задачи с повышенными правами (например, как `sudo`)

Как проверить подключение ко всем серверам из инвентарного файла::используйте команду:  `ansible all -m ping`

Как использовать переменные `ansible_user` и `ansible_group` в playbook::эти переменные можно использовать для указания владельца и группы файла.
