# Upgrade IOS on CISCO ASR901
version 04.02.2023

скрипт для:
- удаления старых образов IOS с CSG
- squeeze
- копирование новых образов

arguments:

- **cfg**: cfg mode

- список всех IOS
- проверить SFP на UPLINK, вендор Cisco ?
- удалить старые IOS, показать какие остались
- squeeze
- SFP если не Cisco запрятить обновление
- проверить есть ли IOS в Flash
    - если нет проверить Free Space
    - скопировать
- проверить на MD5
- asr901-universalk9-mz.156-2.SP9.bin - основной
- asr901-universalk9-mz.155-3.S10.bin - резервный, основной для PAGG XE