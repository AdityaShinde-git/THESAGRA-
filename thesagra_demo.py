from thesagra import DatabaseFile


def main():
    path = "thesagra_demo.tsg"
    db = DatabaseFile.create(path)
    page_id = db.allocate_page()
    db.write_records(
        page_id,
        [
            (1, "Ada", True, None),
            (2, "Linus", False, 3.5),
            (3, "Grace", True, b"\x00\xff"),
        ],
    )

    reopened = DatabaseFile.open(path)
    print(reopened.read_records(page_id))


if __name__ == "__main__":
    main()
