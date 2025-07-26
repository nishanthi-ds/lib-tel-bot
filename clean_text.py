from guessit import guessit
import re

class CleanFilename:

    def __init__(self):
        pass

    # Detects the pattern type of the movie filename and cleans the filename
    def detect_filename_pattern(self, file_name):

        # Underscore-separated
        if file_name.count('_') >= 2:
            file_name = file_name.replace("_", " ")

        # Dot-separated
        elif file_name.count('.') >= 2:
            file_name = file_name.replace(".", " ")

        # Hyphen-separated with brackets (likely uploader format)
        elif '-' in file_name:
            file_name = file_name.replace("-", " ")
            file_name = re.sub(r'^[\w\d.-]+\s*-\s*', '', file_name)

        # Space-separated
        elif ' ' in file_name:
            file_name = file_name.replace(".", " ")

        # Remove @user or @channel patterns
        file_name = re.sub(r"^@\S+\s*", "", file_name)
        file_name = re.sub(r'@\S+', '', file_name)

        # Replace multiple spaces with one
        file_name = re.sub(r"\s{2,}", " ", file_name)

        # Remove unwanted words
        remove_text = ['HDRip', '1080p', '720p', '480p']
        for word in remove_text:
            file_name = file_name.replace(word, "")

        # Remove non-breaking space
        file_name = file_name.replace('\u00a0', ' ')

        return file_name.strip()

    # Extract season-episode like S01E02 if present
    def find_season_episode(self, text):
        for token in text.split():
            match = re.search(r'S\d{1,3}E\d{1,3}', token, re.IGNORECASE)
            if match:
                return match.group()
            else:
                match = re.search(r"season\s*(\d+)\s*episode\s*(\d+)", text, re.IGNORECASE)
                if match:
                    season = int(match.group(1))
                    episode = int(match.group(2))
                    return f"S{season:02d}E{episode:02d}"
        return None

    async def extract_with_guessit(self, filename):
        try:
            if not isinstance(filename, str):
                raise TypeError("Input must be a string representing the filename.")

            result = guessit(filename)
            title = result.get('title')
            year = result.get('year')
            season_episode = self.find_season_episode(filename)

            return title, year, season_episode

        except Exception as e:
            print(f"Error extracting with guessit for '{filename}': {e}")
            return None, None, None

# ---------------------- Async Interface ---------------------- #
async def get_cleantext(file_name):
    clean = CleanFilename()
    file_name = clean.detect_filename_pattern(file_name)
    movie_title, year, seas_epi = await clean.extract_with_guessit(file_name)
    return movie_title, year, seas_epi


# if __name__ == "__main__":
#     with open('movies.json', 'r', encoding='utf-8') as f:
#         movies = json.load(f)

#     clean = CleanFilename()
#     for movie in movies:
        
#         for file in movie["files"]:
#             file_name = file["file_name"]
#             file_name = clean.detect_filename_pattern(file_name)
#             movie_title, year, seas_epi = clean.extract_with_guessit(file_name)
#             print(movie_title, year, seas_epi)

            

# normal --- movie (year)   --- Mufasa The Lion King (2024) [Tamil   720p HQ HDRip   x26~ MR.mkv
# underscore --- movie_year        ---  MLM_The_Jungle_Book_1967720p_BDRip_Tamil_+_Telugu_+_Hindi_+_Eng.mkv
# @user dash --- @user - movie (year) --- @TamilMob_LinkZz -Kung Fu Panda 3 (2016) BluRay - 1080p - x2.mkv
# dot --- @user.year. --- @WMR_Pudhupettai.2006.Tamil.720p.HDRip.x265.Hevc.mkv
# @user underscore --- @user_year_  ------
# S04E08