#!/usr/bin/env python
# coding: utf-8

# The MIT License (MIT)

# Copyright (c) 2015 Pavel Vomacka

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from __future__ import print_function

import argparse
import os
import sys
import re
import subprocess, shlex
from threading import Timer
import sqlite3

manpage_groups = ("1", "8",)


# Name of output file.
db_file = "switch.sqlite3"
# Database path
db_path = "/tmp/switchTest/"

# Database schema
schema_file = "./schema.sql"
opened_db = None

def err_print(*args, **kwargs):
    """
        Print to stderr.
    """
    print(*args, file=sys.stderr, **kwargs)


def create_empty_db():
    """
        Prepare empty database.
    """
    global opened_db

    database_file = os.path.join(db_path, db_file)
    print("\tCreating new database file " + database_file)

    if not os.path.exists(db_path):
        os.makedirs(db_path)

    with sqlite3.connect(os.path.join(db_path, db_file)) as opened_db:
        print("\t\tImporting database schema...")
        with open(schema_file, 'rt') as schema_f:
            schema = schema_f.read()

        # Aplly the schema.
        opened_db.executescript(schema)

def open_db():
    """
        Open DB file.
    """
    global opened_db
    database_file = os.path.join(db_path, db_file)
    print("\tOpening DB file: " + database_file)

    opened_db = sqlite3.connect(database_file)

    curs = opened_db.cursor()

    # Check whether correct tables exists in db
    curs.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND ("
    "name=? OR name=? OR name=?);", ('system', 'command', 'switch',))

    table_count = curs.fetchone()[0]

    if table_count != 3:
        raise RuntimeError


def add_system(sys_name):
    """
        Add system record.
    """
    curs = opened_db.cursor()

    curs.execute("INSERT INTO system(name) VALUES(?)", (sys_name,))

    opened_db.commit()

    return curs.lastrowid


def find_system(sys_name):
    """
        Find system id.
    """
    curs = opened_db.cursor()

    curs.execute("SELECT id FROM system WHERE name=?", (sys_name,))

    return curs.fetchone()


def handle_system(sys_name):
    """
        Handle system.
    """
    system = find_system(sys_name)

    if system is None:
        system = add_system(sys_name)
    else:
        system = system[0]

    return system



def add_command(manpage_name, command, group, sys_id):
    """
        Add command record.
    """
    curs = opened_db.cursor()

    # Handle situation when we are finding record for command --help output.
    if group is not None:
        group = str(group)

    curs.execute("INSERT INTO command(command, manpage_name, man_group, system_id) "
                "VALUES(?,?,?,?)", (command, manpage_name, group, str(sys_id),))

    opened_db.commit()

    return curs.lastrowid


def find_command(command, group, os_id):
    """
        Find command record for correct OS.
    """
    curs = opened_db.cursor()

    # Handle situation when we are finding record for command --help output.
    if group is None:
        curs.execute("SELECT id FROM command WHERE command=? AND system_id=?",
                     (command, os_id,))
    else:
        curs.execute("SELECT id FROM command WHERE command=? AND "
                    "man_group=? AND system_id=?",
                    (command, group, os_id,))



    return curs.fetchone()


def handle_command(manpage_name, command, group, os_id):
    """
        Handle adding commands, in case that command already exists
        also remove all switches which are associated with current command
    """
    command_id = find_command(command, group, os_id)

    if command_id is None:
        # Command is not in database. Add it and use the new ID
        command_id = add_command(manpage_name, command, group, os_id)
    else:
        # Command already exists so use its record id and remove
        # all associated switches.
        command_id = command_id[0]
        delete_associated_switches(command_id)

    return command_id

def store_cmds_to_db(cmds, os_id):
    """
        Store all commands from compgen -c command to database also in case that
        we don't run --help for each command. It helps with testing of commands.
    """
    for cmd in cmds:
        handle_command(None, cmd, None, os_id)


def get_all_commands():
    """
        Get all already inserted commands
    """
    curs = opened_db.cursor()

    curs.execute("SELECT command FROM command;")

    return curs.fetchall()


def add_switch(switch, com_id):
    """
        Add switch record.
    """
    curs = opened_db.cursor()

    curs.execute("INSERT INTO switch(switch, command_id) "
                "VALUES(?,?)", (switch, str(com_id),))

    opened_db.commit()


def delete_associated_switches(command_id):
    """
        Delete all switches associated to the particular command.=
    """
    curs = opened_db.cursor()

    curs.execute("DELETE FROM switch WHERE command_id=?", (command_id,))

    opened_db.commit()


def prepare_dir_regex():
    """
        Prepare regex for getting directories which numbers are defined by
        global variables.
    """
    regex_begin = r"^(?:"
    regex_end = r")$"
    regex = regex_begin

    for group_num in manpage_groups:
        regex = regex + r"(?:man" + group_num + ")|"

    regex = re.sub(r'\|$', '', regex)
    regex = regex + regex_end

    return regex


def get_directories():
    """
        Function that fetch all needed directory names.
    """
    directories = []
    dir_regex = prepare_dir_regex()

    # Load all directories and files in /usr/share/man.
    for root, dirs, files in os.walk('/usr/share/man'):
        # Go through all directory names
        for directory in dirs:
            # Prepare regexp which match to all directories which starts by 'man'
            dirRegexp = re.compile(dir_regex)
            if dirRegexp.match(directory) is None:
                # Skip all directories which does not match regexp
                continue

            # All directories names which match the regexp concatenate with path
            # and save them into list.
            directories.append(os.path.join(root, directory))
        # Do not go deeper into subdirectories.
        break

    # Return list with directories
    return directories


def get_file_names(directories):
    """
        Function that get names of all files in 'directories'.
    """
    files = []

    # Go through all directories
    for directory in directories:
        # Fetch all directories and files in current directory
        for r, d, f in os.walk(directory):
            # Go through all files.
            for ccc in f:
                # Add path to the file to the list
                files.append(r + "/" + ccc)
    # Return filled list.
    return files


def parse_name(content):
    """
        Finds the name of the man page.
    """
    # Create regular expression
    name_regex = re.compile(r"^([\w\.-]*)")
    # Get name of manual page
    just_name = name_regex.search(content)
    name_str = ""

    if just_name is not None:
        name_str = just_name.group(1)

    return name_str


def parse_manpage_number(path):
    """
        Parse number of man page group.
    """
    # Create regular expression
    number_regex = re.compile(r".*/man(\d).*")
    # Get number of manpage group
    number = number_regex.search(path)

    only_number = ""
    if number is not None:
        number = number.group(1)

    return number


def parse_one_page(content):
    """
        Parse flags from manpage which is in content parameter.
    """
    # Create regular expression for getting flags from file \s{1,}
    flag_regex = re.compile(r"(?:\n?(?:(?:[^\w\-])|(?:\[))((?:(?:\-{1,2})|(?:\+))[#\?\w\-\+]*)"
                            "(?:(?:,?\s((?:(?:\-{1,2})|(?:\+))[#\?\w\-\+]+))"
                            "|(?:.*?\s((?:(?:\-{1,2})|(?:\+))[#\?\w\-\+]+)))?)"
                            "|(?:[\[\{]((?:(?:\-{1,2})|(?:\+))[^ ]*?)[\|,\]\}]"
                            "(?:((?:(?:\-{1,2})|(?:\+))}[^ ]*?)[\]\}])?)+")
    flag_list = flag_regex.findall(content)

    # Prepare empty list.
    parsed_flags = []
    # Create regex for checking whether flag contains at least one letter
    # or '#' or question mark.
    check_regexp = re.compile(r"(?:.*?[\w#\?]+.*?)|(?:\-\-)")
    # Go through all flags (flags can be in tuple.)
    for flags in flag_list:
        # Go through each tuple.
        for flag in flags:
            # Check flag.
            if check_regexp.match(flag):
                #Add flag into list.
                #print(flag)
                parsed_flags.append(flag)

    # Remove duplicates
    parsed_flags = list(set(parsed_flags))

    # Return flag which was found.
    return parsed_flags


def parse_bash_page(content, command_list, os_id):
    """
        Parse bash manpage, which is different and keeps switches for more commands.
    """
    #regex for SHELL BUILTIN COMMANDS
    shell_builtins = re.compile(r"^SHELL BUILTIN COMMANDS$")
    # subcommands has 7 spaces before its name.
    builtin_reg = re.compile(r"^ {6,8}([a-zA-Z0-9_\-\+]+)")
    # Match the end of section
    section_end = re.compile(r"^[A-Z]")
    man_group = 1
    builtins = False
    first_line = False
    current_builtin = ""
    bash_man = ""
    mans = {}

    for line in content.splitlines():
        if not builtins:
            if shell_builtins.match(line):
                builtins = True
                # add bash and so far concatenated manpage to table
                mans['bash'] = bash_man
            else:
                bash_man = bash_man + line
        else:
            if builtin_reg.match(line):
                # builtin command
                first_word = builtin_reg.findall(line)[0]
                if first_word in command_list:
                    # first word is correct command
                    current_builtin = first_word
                    mans[current_builtin] = first_word
                    continue
            elif section_end.match(line):
                # next section end whole for cycle
                break

            if current_builtin != "":
                mans[current_builtin] = mans[current_builtin] + line

    # parse mans
    for command in mans:
        flags = parse_one_page(mans[command])
        put_manpage_into_db(os_id, None, command, man_group, flags)


def store_helps(os_id, helps):
    """
        Store options from help outputs to DB.
    """
    for command, manpage in helps.iteritems():
        f_list = parse_one_page(manpage)

        put_manpage_into_db(os_id, None, command, None, f_list)


def put_manpage_into_db(os_id, man_name, command, number, flags_list):
    """
        Insert manpage into database.
    """
    command_id = handle_command(man_name, command, number, os_id)

    for flag in flags_list:
        add_switch(flag, command_id)


def parse_man_pages(files, builtins, os_id):
    """
        Parse all manpages which are accessible by the path in 'path' parameter list.
    """
    # Define variables with tools for reading files.
    reader = "zcat "
    zipped_files = "zcat "
    not_zipped_files = "cat "
    commands_stored = []

    # Open /dev/null/ for output of groff
    f_devnull = open(os.devnull, 'w')

    # Check all files.
    for file_path in files:
        # clean vars
        flags_list = None
        man_name = None
        command = None
        number = None
        """ zcat " + f + " | groff -mandoc -Tutf8
            SOME ERRORS OCCURE WHILE GROFF READING MANPAGES --- ADJUST LINE
            ^^ those errors are caused by mistakes in manpages
        """
        # Check whether the file is zipped or not.
        zipped = re.compile(r".*\.gz$")
        if zipped.match(file_path):
            reader = zipped_files
        else:
            reader = not_zipped_files


        # Check whether there is redirection. If it is then parse name from the path.
        file_name_changed = False
        check_file = subprocess.Popen(shlex.split(reader + file_path), stdout=subprocess.PIPE).communicate()[0]
        if re.match("\.so", check_file):
            file_name_changed = True

            # Create regex for getting name of file.
            reg_name = re.compile(r".*/(.*?)\.\w{1,5}\.gz")
            # Parse path.
            parsed_path = reg_name.search(file_path)
            # Variable for saving name.
            man_name = None
            # If there is at least one match then save it to the variable.
            if parsed_path is not None:
                man_name = parsed_path.group(1)

            # Create regex which catch new file name.
            new_file_regex = re.compile(r".* (.*)")

            # Parse file.
            n_f_search = new_file_regex.search(check_file)

            # Prepare variable.
            new_file = None

            # If there is at least one match then save it to the prepared variable.
            if n_f_search is not None:
                new_file = n_f_search.group(1)
                # Add .gz extension.
                new_file = new_file + ".gz"

            # Substitute old file name by new file name.
            if re.match(r".*/.*", new_file):
                file_path = re.sub(r"/[-\.\w]*/[-\.\w]*$", "/" + new_file, file_path)
            elif re.match(r"[^/]*", new_file):
                file_path = re.sub(r"/[-\.\w]*$", "/" + new_file, file_path)

        p1 = subprocess.Popen(shlex.split(reader + file_path),
                                    stdout=subprocess.PIPE,
                                    universal_newlines=True)
        # Run these two commands connected by pipe.
        """
            Error output is redirected to /dev/null because of warnings from
            incorrectly formated manpages
        """
        output = subprocess.Popen(shlex.split("groff -E -c -mandoc -Tutf8"),
                                        stdin=p1.stdout,
                                        stdout=subprocess.PIPE,
                                        stderr=f_devnull,
                                        universal_newlines=True).communicate()[0]

        number = parse_manpage_number(file_path)

        # Parse name of manpage.
        if not file_name_changed:
            man_name = parse_name(output)

        # \u001B is escape character - character which make colors in man pages
        output = re.sub(u"\u001B\[[^-]*?;?[^-]*?m", "", output)

        if man_name == 'BASH':
            parse_bash_page(output, builtins, os_id)
            continue # manpage is put into db directly in previous function

        # Get list of flags for this page
        flags_list = parse_one_page(output)

        # Consider manpage name as the name of command.
        command = man_name.lower()

        put_manpage_into_db(os_id, man_name, command, number, flags_list)
        commands_stored.append(command)

    f_devnull.close()
    return commands_stored


def get_os_commands(ctype=None):
    """
        Get bash builtin functions
        @param type string could be 'builtin'
    """
    command = "compgen -c"
    if (ctype == 'builtin'):
        command = 'compgen -b'

    p = subprocess.Popen(command,
                              shell=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              stdin=subprocess.PIPE,
                              universal_newlines=True
                              )
    output = subprocess.Popen(["sort", "-u"],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              stdin=p.stdout,
                              universal_newlines=True
                              ).communicate()[0]


    output = output.split('\n')
    regex = re.compile(r'[a-zA-Z]')

    for o in output:
        if not regex.match(o):
            output.remove(o)

    return output


def remove_already_found_cmds(cmds, cmds_in_db):
    """
        Remove commands which are already in database
    """
    for cmd in cmds_in_db:

        if cmd in cmds:
            cmds.remove(cmd)

    return cmds


def handle_helps(os_id, cmds):
    """
        Call --help on each command which has not been processed yet
    """
    help_cont = ''
    timeout = 2
    helps = {}
    for cmd in cmds:
        try:
            p = subprocess.Popen([cmd, "--help"],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT,
                                      stdin=subprocess.PIPE,
                                      universal_newlines=True
                                      )
            kill_proc = lambda p: p.kill()
            timer = Timer(timeout, kill_proc, [p])
            try:
                timer.start()
                help_cont = p.communicate()[0]
            finally:
                timer.cancel()

        except OSError:
            err_print("ERROR in running '" + cmd + " --help'.")
            continue

        f_list = parse_one_page(help_cont)

        put_manpage_into_db(os_id, None, cmd, None, f_list)

        helps[cmd] = help_cont

    return helps


def parse_options():
    """
        Parse options
    """
    parser = argparse.ArgumentParser(description="Generate SQLite3 database "
                                     "with all options and switches for all "
                                     "installed commands.")
    parser.add_argument("--from-help", help="WARNING: Use this parameter only on "
                        "virtual machine, which could be lost. Try to run all "
                        "found commands with '--help' parameter to fetch all "
                        "options from the output. Please use this only if you "
                        "know what you are doing. ",
                        action="store_true")
    parser.add_argument("--os-name", help="Name of the OS. Whole name will be "
                        "created by concatenating OS name and OS version.",
                        required=True)
    parser.add_argument("--os-version", help="Version of OS. Whole name will be "
                        "created by concatenating OS name and OS version.",
                        required=True)
    parser.add_argument("--schema-file", default="./schema.sql",
                        help="File with database schema. Default file: "
                        "./schema.sql")
    parser.add_argument("--db-file", default="switch.sqlite3",
                        help="The name of the database file.")
    parser.add_argument("--output-db-dir", default="/tmp/switchTest",
                        help="Directory to write generated database to. "
                        "Default directory: /tmp/switchTest/")
    prog_args = parser.parse_args()

    # Name of schema file.
    if prog_args.schema_file:
        global schema_file
        schema_file = prog_args.schema_file

    # Name of database file.
    if prog_args.output_db_dir:
        global db_path
        db_path = prog_args.output_db_dir

    # DB path
    if prog_args.db_file:
        global db_file
        db_file = prog_args.db_file

    return prog_args


def main():
    """
        Main funciton.
    """

    # Parse options
    args = parse_options()

    # Check Python version
    if sys.version_info[0] != 2:
        raise Exception("Must be using Python 2")

    print("Preparing database file...")
    # Create empty database in case that db file does not exists
    if os.path.exists(os.path.join(db_path, db_file)):
        open_db()
    else:
        create_empty_db()

    print("Searching OS ID...")
    current_os_id = handle_system(args.os_name + args.os_version)

    print("Fetching directories with manual pages...")
    # Get directories with manual pages
    directories = get_directories()
    # Get names of manpage files.
    files = get_file_names(directories)

    print("Fetching builtin commands...")
    # Get bash builtin functions
    builtins = get_os_commands('builtin')
    # Get all runnable commands - get all runable commands
    cmds = get_os_commands()

    print("Parsing manual pages...")
    # Parse man pages
    handled_cmds = parse_man_pages(files, builtins, current_os_id)

    # Compare list of commands found in OS with all already stored in DB.
    # Then remove all commands which are already in DB from list of all commands.
    remove_already_found_cmds(cmds, handled_cmds)

    print("Storing commands from 'compgen -c' command...")
    store_cmds_to_db(cmds, current_os_id)

    # Call each command which is not in DB yet with '--help' param to gather
    # further data.
    if args.from_help:
        print("Running commands with --help option...")
        helps = handle_helps(current_os_id, cmds)


"""
    Run main function.
"""
if __name__ == "__main__":
	main()
