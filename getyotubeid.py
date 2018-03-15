import re


def get_youtube_id(text, first_match=True, fuzzy=True):
    """Try to find the YouTube ID in the given text.

    Note: If first_match=False and fuzzy=True, you may get some false results.

    Args:
        text (str): Text which may contains a youtube url.
        first_match (bool, optional): Defaults to True. Return only the first result.
            If it False, returns a tuple with all the results.
        fuzzy (bool, optional): Defaults to True. Deeper search.

    Returns:
        [str | tuple | None]: The ID/IDs in string/tuple if found, else None.
    """

    base_pattern = re.compile(r'youtu\.?be')       # youtube | youtu.be

    patterns = [
        re.compile(r'youtu\.be\/([^#\&\?]{11})'),  # youtu.be/<id>
        re.compile(r'\?v=([^#\&\?]{11})'),         # ?v=<id>
        re.compile(r'\&v=([^#\&\?]{11})'),         # &v=<id>
        re.compile(r'embed\/([^#\&\?]{11})'),      # embed/<id>
        re.compile(r'\/v\/([^#\&\?]{11})'),        # /v/<id>
    ]

    fuzzy_pattern = re.compile(r'[\/\&\?=#\.\s]')  # split by: /, &, ?, =, #, ., whitespace

    id_pattern = re.compile(r'^[^#\&\?]{11}$')     # pure youtube ID pattern

    results = []

    # Check if we have any youtube related string in the text.
    if len(base_pattern.findall(text)) > 0:
        # Try all the patterns.
        for pattern in patterns:
            result = pattern.findall(text)

            for match in result:
                results.append(match)

        if fuzzy:
            for text_parts in fuzzy_pattern.split(text):
                result = id_pattern.findall(text_parts)

                for match in result:
                    results.append(match)

        if len(results) > 0:
            if first_match:
                return results[0]

            # If we have to return the whole list, make it uniqe.
            return tuple(set(results))

    return None
