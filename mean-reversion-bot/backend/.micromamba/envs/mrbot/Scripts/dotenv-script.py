#!C:\Users\win\Desktop\mean-reversion-bot_2\mean-reversion-bot\backend\.micromamba\envs\mrbot\python.exe
# -*- coding: utf-8 -*-
import re
import sys

from dotenv.__main__ import cli

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(cli())
