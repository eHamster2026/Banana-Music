from services.artist_names import artist_names_from_tag_dict


def test_artist_names_from_tag_dict_preserves_tag_artist_list():
    assert artist_names_from_tag_dict({"artists": ["陶喆", "A-Lin", "陶喆"]}) == ["陶喆", "A-Lin"]
