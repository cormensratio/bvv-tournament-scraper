import hashlib
import json
import re
import smtplib
import ssl
from collections import defaultdict
from datetime import datetime
from email.mime.text import MIMEText
from enum import Enum
from os.path import isfile
from typing import Type

import requests
from bs4 import BeautifulSoup, Tag

type UserConfig = dict[str, str | dict[int, str], dict[str, str]]
type TournamentType = dict[str, str]

# TODO: rework CLI inputs with argparse or click library

# naive email regex
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")

USER_CONFIG_JSON_NAME = "user-config.json"
TOURNAMENT_JSON_NAME = "tournament-data.json"


# TODO: Introduce a Tournament class

class VolleyballEnumType(Enum):
    @classmethod
    def __subclasshook__(cls, subclass: Type) -> bool:
        if cls is VolleyballEnumType:
            return issubclass(subclass, Enum)
        return NotImplemented


class PlayingStyle(VolleyballEnumType):
    MEN = "Männer"
    WOMEN = "Frauen"
    MIXED = "Mixed"


# TODO: auto explore tournament classes from site
class TournamentClass(VolleyballEnumType):
    KAT_1_PLUS = "BVV Beach Masters (Kat.1+)"
    KAT_1 = "BVV Beach Masters (Kat.1)"
    KAT_2 = "BVV Beach Masters (Kat.2)"
    KAT_3_CUP_PLUS = "BVV Beach K3 (Cup+)"
    SONSTIGE_MIXED = "sonstige Mixed"
    EXPERT_MIXED = "Expert - Mixed"
    FREESTYLE = "Freestyle"
    BASIC = "basic"
    EXPERT = "expert"
    CUSTOM = "custom"


def __yes_no_parser() -> bool:
    while True:
        yes_no_str: str = input(f"(Y)es/no\n").lower().strip()

        if yes_no_str in ["yes", "y"] or not yes_no_str:
            return True

        if yes_no_str in ["no", "n"]:
            return False

        print("Given input not recognized. Please try again.")


def __print_enum_selection(enum: type[VolleyballEnumType], idx_count_start: int) -> None:
    print('\n'.join([f"({idx}) {c.value}" for idx, c in enumerate(enum, start=idx_count_start)]))


def __parse_enum_selection(enum: type[VolleyballEnumType]) -> list[int]:
    num_entries: int = len(enum)
    final_selection: set[int] | list[int] = set()

    print(
        "\nSelect by typing the number and press ENTER after each selection or select X and press ENTER to finish "
        "your selection:")

    while True:
        if len(final_selection) == num_entries:
            return list(final_selection)

        selection: int | str = input().strip()

        if selection.strip().lower() == "x":
            if len(final_selection) == 0:
                print("You have to select at least one item.")
                continue
            return list(final_selection)

        if not selection.isdigit() or int(selection) < 0 or int(selection) >= num_entries:
            print(f"You have to choose a number from the selection between 0 and {num_entries - 1}.")
        else:
            final_selection.add(int(selection))


def __get_entries_by_numbers(enum: type[VolleyballEnumType], class_numbers: list[int]) -> list[VolleyballEnumType]:
    return [list(enum)[idx] for idx in class_numbers]


def __map_numbers_to_entry_values(enum: type[VolleyballEnumType], entry_numbers: list[int]) -> dict[int, str]:
    mapping: dict[int, str] = {}

    for idx in entry_numbers:
        mapping[idx] = list(enum)[idx].value

    return mapping


def __classes_to_full_name(classes: list[TournamentClass]) -> list[str]:
    return list(map(lambda c: c.name, classes))


def __parse_playing_style(config: UserConfig) -> UserConfig:
    print("Choose one or multiple playing styles from the list:")

    __print_enum_selection(PlayingStyle, 0)
    playing_style_numbers: list[int] = __parse_enum_selection(PlayingStyle)

    config["playingStyle"] = __map_numbers_to_entry_values(PlayingStyle, playing_style_numbers)

    return config


def __parse_email_details(config: UserConfig) -> UserConfig:
    print(f"\nDo you want to receive email notifications about new tournaments?\n")

    is_email_notification: bool = __yes_no_parser()

    if not is_email_notification:
        return config

    def parse_email_address() -> str:
        retry_email: bool = True

        while retry_email:
            from_email: str = input(f"Please enter your email address: ")

            if not EMAIL_REGEX.fullmatch(from_email):
                print("Invalid email address. Do you still want to continue with this email?")

                if not __yes_no_parser():
                    continue

            # Return with or without valid email address
            return from_email

    config["email"]["from"] = parse_email_address()
    config["email"]["to"] = config["email"]["from"]  # same as from if not specified otherwise

    print(
        "\nThis application uses your own email address to notify you. "
        "Hence, it needs your password, which will be stored in a config.json file with the rest of your input data.")

    password: str = input("Please enter your email password: ")
    config["email"]["password"] = password

    # TODO: extract automatically from email address OR select from list
    email_host: str = input(
        f"Type in the host name of your remote email provider, such as 'smtp.gmail.com' for Gmail.\n")

    config["email"]["host"] = email_host

    print("Do you want to receive your tournament alert at another email address than your sender address?\n")

    if __yes_no_parser():
        config["email"]["to"] = parse_email_address()

    return config


def __parse_tournament_classes(config: UserConfig) -> UserConfig:
    print("\nChoose one or multiple tournament classes from the list or use the 'custom' option to define your own.")
    __print_enum_selection(TournamentClass, 0)
    class_numbers: list[int] = __parse_enum_selection(TournamentClass)
    tournament_classes: list[VolleyballEnumType] = __get_entries_by_numbers(TournamentClass, class_numbers)

    # TODO: implement custom
    if TournamentClass.CUSTOM in tournament_classes:
        raise NotImplementedError("The support for custom classes is currently not supported.")

    config["classes"] = __map_numbers_to_entry_values(TournamentClass, class_numbers)

    return config


def parse_user_config() -> UserConfig:
    config: UserConfig = defaultdict(dict)

    __parse_playing_style(config)
    __parse_email_details(config)
    __parse_tournament_classes(config)

    return config


def __dump_to_json(data: dict | list[dict], filename: str) -> None:
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, fp=f, sort_keys=True, ensure_ascii=False, indent=4)


def __load_from_json(filename: str) -> dict:
    with open(filename) as f:
        return json.load(f)


def __generate_uid_from_tournament(tournament: TournamentType) -> str:
    combined_string = ''.join(map(str, tournament.values()))
    return hashlib.sha256(combined_string.encode()).hexdigest()


def __tournament_to_str(tournament: TournamentType) -> str:
    result: str = ""

    result += f"Class: {tournament["class"]}\n"
    result += f"Date: {tournament["date"]}\n"
    result += f"Location: {tournament["location"]}\n"
    result += f"Playing style: {tournament["playingStyle"]}\n"
    result += f"Number of teams: {tournament["numberTeams"]}\n\n"

    return result


def __tournaments_to_str(tournaments: list[TournamentType]) -> str:
    return f"Tournament details:\n------------------------------------\n{''.join(map(__tournament_to_str, tournaments))}"


def scrape_relevant_tournaments(config: UserConfig) -> dict[str, TournamentType]:
    bvv_beach_tournament_page = requests.get(f"https://volleyball.bayern/beach/turniere/{datetime.now().year}/")
    bvv_beach_tournament_page.raise_for_status()

    soup = BeautifulSoup(bvv_beach_tournament_page.text, 'html.parser')
    all_classes_tags: list[Tag] = soup.find_all("div", {"class": "bvv_rangliste bvv_ranglistebox"})

    # Filter for classes specified by the user
    relevant_class_tags_by_name: dict[str, Tag] = {}
    for t in all_classes_tags:
        class_name = t.find("h3").text

        if class_name in config["classes"].values():
            relevant_class_tags_by_name[class_name] = t

    scraped_tournaments: dict[str, TournamentType] = dict(defaultdict(dict))

    for class_name, tag in relevant_class_tags_by_name.items():
        tbody = tag.find("tbody")

        for tr in tbody.find_all("tr"):
            row_data = tr.find_all("td")

            playing_style: str = row_data[3].text

            # Skip row if not user specified playing style
            if playing_style not in config["playingStyle"].values():
                continue

            tournament: TournamentType = defaultdict()

            tournament["class"] = class_name
            tournament["date"] = row_data[0].text
            # Skip empty td at row_data[1]
            tournament["location"] = row_data[2].text
            tournament["playingStyle"] = playing_style
            tournament["numberTeams"] = row_data[4].text

            tournament_uid = __generate_uid_from_tournament(tournament)
            scraped_tournaments[tournament_uid] = tournament

    return scraped_tournaments


def __send_email(user_config: UserConfig, tournament_data: list[TournamentType]) -> None:
    try:
        msg = MIMEText(
            f"There are {len(tournament_data)} new tournaments to apply!\n\n{__tournaments_to_str(tournament_data)}",
            _subtype="plain")

        msg['Subject'] = 'BVV Tournament Alert!'
        msg['From'] = user_config["email"]["from"]
        msg['To'] = user_config["email"]["to"]

        context = ssl.create_default_context()
        port: int = 587

        with smtplib.SMTP(host=user_config["email"]["host"], port=port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(user_config["email"]["from"], user_config["email"]["password"])
            server.ehlo()
            server.sendmail(user_config["email"]["from"], user_config["email"]["to"], msg.as_string())
            server.quit()
    except Exception as e:
        print(f"An error occurred: {e}")


def __parse_intro() -> None:
    print("\nWelcome to the BVV tournament scraper! Never miss out on any tournament registrations again :)\n")
    print("Do you want create/update your user config?")
    update_user_config: bool = __yes_no_parser()

    user_config_exists: bool = isfile(USER_CONFIG_JSON_NAME)
    user_config: UserConfig

    if update_user_config or not user_config_exists:
        if not user_config_exists:
            print("It seems that you have no user config created yet. This will only take a few seconds.\n")

        user_config = parse_user_config()
        __dump_to_json(user_config, USER_CONFIG_JSON_NAME)
    else:
        user_config = __load_from_json(USER_CONFIG_JSON_NAME)

    print("Processing...\n")

    scraped_tournament_data: dict[str, TournamentType] | None = scrape_relevant_tournaments(user_config)
    tournament_data_exists: bool = isfile(TOURNAMENT_JSON_NAME)

    if not tournament_data_exists:
        print(
            "It seems that this is your first time gathering your tournament data. Do you want to view all available tournaments you are interested in?")
        show_all_tournaments: bool = __yes_no_parser()

        if show_all_tournaments:
            print("You're welcome:\n")
            print(__tournaments_to_str(list(scraped_tournament_data.values())))

        __dump_to_json(scraped_tournament_data, TOURNAMENT_JSON_NAME)

        print(
            "The next time you run this application, you will only get notified about new tournaments you have not yet seen.")

    else:
        loaded_tournament_data = __load_from_json(TOURNAMENT_JSON_NAME)
        __dump_to_json(scraped_tournament_data, TOURNAMENT_JSON_NAME)
        keys_diff: set[str] = set(scraped_tournament_data.keys()) - set(loaded_tournament_data.keys())

        num_new_tournaments: int = len(keys_diff)

        print(f"There are {num_new_tournaments} new tournaments!")

        if num_new_tournaments > 0:
            print("Do you want to show them?")
            new_tournaments: [TournamentType] = [scraped_tournament_data[k] for k in scraped_tournament_data.keys() if
                                                 k in keys_diff]
            if __yes_no_parser():
                print(__tournaments_to_str(new_tournaments))

            # TODO: check presence of all required values
            # if all(user_config["email"], [user_config["email"]["from"], user_config["email"]["password"]]):
            __send_email(user_config, new_tournaments)
        else:
            print("You are up to date!")


def main() -> None:
    __parse_intro()
    exit(0)


if __name__ == "__main__":
    main()
    # TODO: Implement non-interactive mode for cronjob setup
    # TODO: transform to OOP
    # TODO: error handling
    # TODO: Implement OAuth2 for Outlook, Google etc. as simple authentication has moved
