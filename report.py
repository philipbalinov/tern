'''
Create a report
'''
import sys

from utils.commands import start_container
from utils.commands import remove_container
from utils.commands import remove_image
import common

# constants
report_file = 'report.txt'
report_confirmed = 'Confirmed sources:\n'
report_unconfirmed = 'Unconfirmed sources:\n'
report_package = '\t{package}\n'
report_url = '\t\turl: {url}\n'
report_version = '\t\tversion: {version}\n'
report_license = '\t\tlicense: {license}\n'
report_unrecog = 'Unrecognized packages:\n'
report_notes = 'NOTES:\n'

# report messages
no_packages = '''Unable to recover packages for layer {layer}.
Consider either entering them manually or create a bash script to retrieve the
package in the command library.\n'''
no_version = '''No version for package {package}.
Consider either entering the version manually or creating a script to retrieve
it in the command library\n'''
no_license = '''No license for package {package}.
Consider either entering the license manually or creating a script to retrieve
it in the command library\n'''
no_src_url = '''No source url for package {package}.
Consider either entering the source url manually or creating a script to
retrieve it in the command library\n'''
env_dep_dockerfile = '''Docker build failed: {build_fail_msg} \n
Since the Docker image cannot be built, Tern will try to retrieve package
information from the Dockerfile itself.\n'''
invoking_from_base = '''
Checking against command_lib/base.yml to retrieve information about packages
in this layer. Some of the results are shell snippets that will be invoked\n'''
checking_against_snippets = '''
Checking against command_lib/snippets.yml to see if there is a listing for
the commands in the Dockerfile RUN line\n'''


def record_report(report_dict):
    '''The report dict will look like this:
        confirmed: [{name: <name>, url: <url>, version: <version>}...]
        unconfirmed:[<package_names>]
        unrecognized: [<list of docker commands>]
    Record the report with each of these values
    If there are no packages, record nothing'''
    report = report_confirmed
    if report_dict['confirmed']:
        for package in report_dict['confirmed']:
            report = report + report_package.format(package=package['name'])
            report = report + report_url.format(url=package['src_url'])
            report = report + report_version.format(version=package['version'])
            report = report + report_license.format(license=package['license'])
    report = report + report_unconfirmed
    if report_dict['unconfirmed']:
        for name in report_dict['unconfirmed']:
            report = report + name + ' '
    report = report + report_unrecog
    if report_dict['unrecognized']:
        for command in report_dict['unrecognized']:
            report = report + '\t' + command + '\n'
    return report


def write_report(report):
    '''Write the report to a file'''
    with open(report_file, 'w') as f:
        f.write(report)


def append_confirmed(packages, report, notes):
    '''Append the report and notes with packaging information for confirmed
    packages. Here the report is a dictionary'''
    for package in packages:
        report['confirmed'].append(package.to_dict())
        if package.version == 0.0:
            notes = notes + no_version.format(package=package.name)
        if package.license == '':
            notes = notes + no_license.format(package=package.name)
        if package.src_url == '':
            notes = notes + no_src_url.format(package=package.name)
    return report, notes


def print_package_notes(packages, report, notes):
    '''Append to the given report package information and notes if the
    information is missing'''
    for package in packages:
        report = report + report_package.format(package=package.name)
        report = report + report_version.format(version=package.version)
        report = report + report_license.format(license=package.license)
        report = report + report_url.format(url=package.src_url)
        if package.version == 0.0:
            notes = notes + no_version.format(package=package.name)
        if package.license == '':
            notes = notes + no_license.format(package=package.name)
        if package.src_url == '':
            notes = notes + no_src_url.format(package=package.name)
    return report, notes


def print_dockerfile_run(report, shell, base_layer_no):
    '''Given the report, the shell used for commands in the built image
    and the number of base layers in the history, retrieve package
    information for each of the dockerfile RUN instructions and append the
    results to the report and return the report
    1. Retrieve the history and the diff ids for the built image and remove
    the first few lines corresponding to the base image. The next line should
    correspond with the first dockerfile line run
    2. For each Dockerfile RUN
        1. Check if the dockerfile run matches the history.
        If yes - that is the layer sha. If not, skip to the next RUN line
        2. Get the run dictionary of commands and packages that were installed
        with them
        3. Retrieve package information for these packages
        4. Create the layer object with this list
        5. Record the layer with package information
        6. Append to the report the Dockerfile line, and the packages retrieved
    '''
    layer_history = common.get_layer_history(common.get_dockerfile_image_tag())
    while base_layer_no > 0:
        layer_history.pop(0)
        base_layer_no = base_layer_no - 1
    for instr in common.docker_commands:
        if instr[0] == 'RUN':
            if instr[1] in layer_history[0][0]:
                # this is the sha for the given layer
                sha = layer_history[0][1]
                run_dict = common.get_confirmed_packages(instr, shell)
                report = report + run_dict['instruction'] + '\n'
                pkg_list = common.get_packages_from_snippets(
                    run_dict['confirmed'], shell)
                if pkg_list:
                    layer_obj = common.build_layer_obj(sha, pkg_list)
                    common.record_layer(layer_obj)
                    report, notes = print_package_notes(pkg_list, report, '')
                    report = report + notes
                else:
                    report = report + no_packages.format(layer=sha)
    return report


def execute_summary(args):
    '''Create a summarized report'''
    report = {}
    notes = ''
    report.update({'confirmed': [], 'unconfirmed': [], 'unrecognized': []})
    if args.dockerfile:
        # parse the dockerfile
        common.load_docker_commands(args.dockerfile)
    base_image_msg = common.get_dockerfile_base()
    notes = notes + base_image_msg[1]
    # get the list of layers in the base image
    base_obj_list = common.get_base_obj(base_image_msg[0])
    for base_obj in base_obj_list:
        if base_obj.packages:
            print('Adding packages from cache...')
            report, notes = append_confirmed(base_obj.packages, report, notes)
        else:
            # see if packages can be extracted
            # TODO: right now it is with the whole base image only
            # i.e. they have only one layer
            print('Nothing in cache. Invoking from command library...')
            package_list = common.get_packages_from_base(base_image_msg[0])
            if package_list:
                common.record_layer(base_obj, package_list)
                report, notes = append_confirmed(base_obj.packages, report,
                                                 notes)
            else:
                notes = notes + no_packages.format(layer=base_obj.sha)
    common.save_cache()
    # get a list of packages that may be installed from the dockerfile
    if common.is_build():
        # TODO: execute the snippets to get the required package info
        print('Build succeeded - running general code snippets')
    else:
        notes = notes + env_dep_dockerfile
        pkg_dict = common.get_dockerfile_packages()
        report['unconfirmed'].extend(pkg_dict['recognized'])
        report['unrecognized'].extend(pkg_dict['unrecognized'])

    report_txt = record_report(report) + '\n' + report_notes + notes
    write_report(report_txt)
    print('Report completed')
    sys.exit(0)


def execute(args):
    '''Create a longform report
    This is the default execution route'''
    report = ''
    if args.dockerfile:
        # parse the dockerfile
        common.load_docker_commands(args.dockerfile)
    # Packages from the base image instructions
    report = report + "Dockerfile base image:\n"
    report = report + common.print_dockerfile_base()
    base_image_msg = common.get_dockerfile_base()
    report = report + base_image_msg[1] + '\n'
    base_obj_list = common.get_base_obj(base_image_msg[0])
    report = report + "Base image layers:\n"
    for base_obj in base_obj_list:
        report = report + base_obj.sha[:10] + ':\n'
        if base_obj.packages:
            report = report + 'A record for this layer exists in the cache:\n'
            print('Adding packages from cache...')
            report, notes = print_package_notes(base_obj.packages, report, '')
            report = report + notes
        else:
            # see if packages can be extracted
            # TODO: right now it is with the whole base image only
            # i.e. they have only one layer
            report = report + invoking_from_base
            report = report + common.print_image_info(base_image_msg[0])
            print('Nothing in cache. Invoking from command library...')
            package_list = common.get_packages_from_snippets(base_image_msg[0])
            if package_list:
                common.record_layer(base_obj, package_list)
                report, notes = print_package_notes(base_obj.packages, report,
                                                    '')
                report = report + notes
            else:
                report = report + no_packages.format(layer=base_obj.sha)
    common.save_cache()
    # get a list of packages that may be installed from the dockerfile
    report = report + 'Packages from current image:\n'
    build, msg = common.is_build()
    if build:
        # get the shell that we will use for all the commands
        shell = common.get_image_shell(base_image_msg[0])
        # start a container with the built image
        image_tag_string = common.get_dockerfile_image_tag()
        start_container(image_tag_string)
        report = print_dockerfile_run(report, shell, len(base_obj_list))
        # remove container when done
        remove_container()
        remove_image(image_tag_string)
    else:
        report = report + env_dep_dockerfile.format(build_fail_msg=msg)
        report = report + checking_against_snippets
        pkg_dict = common.get_dockerfile_packages()
        report = report + 'Packages from parsing Dockerfile RUN commands:\n'
        for pkg in pkg_dict['recognized']:
            report = report + ' ' + pkg
        report = report + '\nUnregonized RUN commands in Dockerfile:\n'
        for cmd in pkg_dict['unrecognized']:
            report = report + cmd + '\n'
    write_report(report)
    sys.exit(0)
