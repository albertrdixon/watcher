import core
import datetime
import logging
import time
import json
import os
import shutil

from core.helpers import Comparisons
from sqlalchemy import *

logging = logging.getLogger(__name__)


class SQL(object):
    '''
    All methods will return False on failure.
    On success they will return the expected data or True.
    '''

    def __init__(self):
        DB_NAME = u'sqlite:///{}'.format(core.DB_FILE)
        try:
            self.engine = create_engine(DB_NAME, echo=False, connect_args={'timeout': 30})
            self.metadata = MetaData()
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e: # noqa
            logging.error(u'Opening SQL DB.', exc_info=True)
            raise

        # These definitions only exist to CREATE tables.
        self.MOVIES = Table('MOVIES', self.metadata,
                            Column('added_date', TEXT),
                            Column('imdbid', TEXT),
                            Column('title', TEXT),
                            Column('year', TEXT),
                            Column('poster', TEXT),
                            Column('plot', TEXT),
                            Column('url', TEXT),
                            Column('score', TEXT),
                            Column('release_date', TEXT),
                            Column('rated', TEXT),
                            Column('status', TEXT),
                            Column('predb', TEXT),
                            Column('quality', TEXT),
                            Column('finished_date', TEXT),
                            Column('finished_score', SMALLINT)
                            )
        self.SEARCHRESULTS = Table('SEARCHRESULTS', self.metadata,
                                   Column('score', SMALLINT),
                                   Column('size', SMALLINT),
                                   Column('category', TEXT),
                                   Column('status', TEXT),
                                   Column('pubdate', TEXT),
                                   Column('title', TEXT),
                                   Column('imdbid', TEXT),
                                   Column('indexer', TEXT),
                                   Column('date_found', TEXT),
                                   Column('info_link', TEXT),
                                   Column('guid', TEXT),
                                   Column('torrentfile', TEXT),
                                   Column('resolution', TEXT),
                                   Column('type', TEXT),
                                   Column('downloadid', TEXT)
                                   )
        self.MARKEDRESULTS = Table('MARKEDRESULTS', self.metadata,
                                   Column('imdbid', TEXT),
                                   Column('guid', TEXT),
                                   Column('status', TEXT)
                                   )

        # {TABLENAME: [(new_col, old_col), (new_col, old_col)]}
        self.convert_names = {'MOVIES':
                              [('url', 'tomatourl'),
                               ('score', 'tomatorating'),
                               ('release_date', 'released'),
                               ('finished_date', 'finisheddate')
                               ]}

    def create_database(self):
        logging.info(u'Creating tables.')
        self.metadata.create_all(self.engine)
        return

    def execute(self, command):
        ''' Executes SQL command
        command: str or list of SQL commands

        We are going to loop this up to 5 times in case the database is locked.
        After each attempt we wait 1 second to try again. This allows the query
            that has the database locked to (hopefully) finish. It might
            (i'm not sure) allow a query to jump in line between a series of
            queries. So if we are writing searchresults to every movie at once,
            the get_user_movies request may be able to jump in between them to
            get the user's movies to the browser. Maybe.

        Returns result of command, or False if unable to execute
        '''

        tries = 0
        while tries < 5:
            try:
                if type(command) == list:
                    result = self.engine.execute(*command)
                else:
                    result = self.engine.execute(command)
                return result

            except Exception as e:
                logging.error(u'SQL Databse Query: {}'.format(command), exc_info=True)
                if 'database is locked' in e.args[0]:
                    logging.info(u'SQL Query attempt # {}'.format(tries))
                    tries += 1
                    time.sleep(1)
                else:
                    logging.error(u'SQL Databse Query: {}'.format(command), exc_info=True)
                    raise
        # all tries exhausted
        return False

    def write(self, TABLE, DB_STRING):
        '''
        Takes dict DB_STRING and writes to TABLE.
        DB_STRING must have key:val matching Column:Value in table.
        Returns Bool on success.
        '''

        logging.info(u'Writing data to {}'.format(TABLE))

        cols = u', '.join(DB_STRING.keys())
        vals = DB_STRING.values()

        qmarks = u', '.join(['?'] * len(DB_STRING))

        sql = "INSERT INTO %s ( %s ) VALUES ( %s )" % (TABLE, cols, qmarks)

        command = [sql, vals]

        if self.execute(command):
            return True
        else:
            logging.error(u'EXECUTE SQL.WRITE FAILED.')
            return False

    def write_search_results(self, LIST):
        '''
        Takes list of dicts to write into SEARCHRESULTS.
        '''

        if not LIST:
            return True

        logging.info(u'Writing batch into SEARCHRESULTS')

        INSERT = self.SEARCHRESULTS.insert()

        command = [INSERT, LIST]

        if self.execute(command):
            return True
        else:
            logging.error(u'EXECUTE SQL.WRITE_SEARCH_RESULTS FAILED.')
            return False

    def update(self, TABLE, COLUMN, VALUE, imdbid='', guid=''):
        '''
        Updates single value in existing table row.
        Selects row to update from imdbid or guid.
        Sets COLUMN to VALUE.
        Returns Bool.
        '''

        if imdbid:
            idcol = u'imdbid'
            idval = imdbid
        elif guid:
            idcol = u'guid'
            idval = guid
        else:
            return 'ID ERROR'

        logging.info(u'Updating {} to {} in {}.'.format(idval, VALUE, TABLE))

        sql = u'UPDATE {} SET {}=? WHERE {}=?'.format(TABLE, COLUMN, idcol)
        vals = (VALUE, idval)

        command = [sql, vals]

        if self.execute(command):
            return True
        else:
            logging.error(u'EXECUTE SQL.UPDATE FAILED.')
            return False

    def get_user_movies(self):
        ''' Gets all info in MOVIES

        Returns list of dicts with all information in MOVIES
        '''

        logging.info(u'Retreving list of user\'s movies.')
        TABLE = u'MOVIES'

        command = u'SELECT * FROM {} ORDER BY title ASC'.format(TABLE)

        result = self.execute(command)

        if result:
            lst = []
            for i in result:
                lst.append(dict(i))
            return lst
        else:
            logging.error(u'EXECUTE SQL.GET_USER_MOVIES FAILED.')
            return False

    def get_movie_details(self, idcol, idval):
        ''' Returns dict of single movie details from MOVIES.
        :param idcol: str identifying column
        :param idval: str identifying value

        Looks through MOVIES for idcol:idval

        Returns dict of first match
        '''

        logging.info(u'Retreving details for {}.'.format(idval))

        command = u'SELECT * FROM MOVIES WHERE {}="{}"'.format(idcol, idval)

        result = self.execute(command)

        if result:
            data = result.fetchone()
            return dict(data)
        else:
            return False

    def get_search_results(self, imdbid, quality):
        ''' Gets all search results for a given movie
        :param imdbid: str imdb id #
        quality: str quality profile. Used to sort order

        Returns list of dicts for all SEARCHRESULTS that match imdbid
        '''

        if quality in core.CONFIG['Quality']['Profiles'] and core.CONFIG['Quality']['Profiles'][quality]['prefersmaller']:
            sort = 'ASC'
        else:
            sort = 'DESC'

        logging.info(u'Retreving Search Results for {}.'.format(imdbid))
        TABLE = u'SEARCHRESULTS'

        command = u'SELECT * FROM {} WHERE imdbid="{}" ORDER BY score DESC, size {}'.format(TABLE, imdbid, sort)

        results = self.execute(command)

        if results:
            return results.fetchall()
        else:
            return False

    def get_marked_results(self, imdbid):
        ''' Gets all entries in MARKEDRESULTS for given movie
        :param imdbid: str imdb id #

        Returns dict {guid:status, guid:status, etc}
        '''

        logging.info(u'Retreving Marked Results for {}.'.format(imdbid))

        TABLE = u'MARKEDRESULTS'

        results = {}

        command = u'SELECT * FROM {} WHERE imdbid="{}"'.format(TABLE, imdbid)

        data = self.execute(command)

        if data:
            for i in data.fetchall():
                results[i['guid']] = i['status']
            return results
        else:
            return False

    def remove_movie(self, imdbid):
        ''' Removes movie and search results from DB
        :param imdbid: str imdb id #

        Doesn't access sql directly, but instructs other methods to delete all information that matches imdbid.

        Removes from MOVIE, SEARCHRESULTS, and deletes poster. Keeps MARKEDRESULTS.

        Returns True/False on success/fail or None if movie doesn't exist in DB.
        '''

        logging.info(u'Removing {} from {}.'.format(imdbid, 'MOVIES'))

        if not self.row_exists('MOVIES', imdbid=imdbid):
            return None

        if not self.delete('MOVIES', 'imdbid', imdbid):
            return False

        logging.info(u'Removing any stored search results for {}.'.format(imdbid))

        if self.row_exists('SEARCHRESULTS', imdbid):
            if not self.purge_search_results(imdbid=imdbid):
                return False

        logging.info(u'{} removed.'.format(imdbid))
        return True

    def delete(self, TABLE, idcol, idval):
        ''' Deletes row where idcol == idval
        :param idcol: str identifying column
        :param idval: str identifying value

        Returns Bool.
        '''

        logging.info(u'Removing from {} where {} is {}.'.format(TABLE, idcol, idval))

        command = u'DELETE FROM {} WHERE {}="{}"'.format(TABLE, idcol, idval)

        if self.execute(command):
            return True
        else:
            return False

    def purge_search_results(self, imdbid=''):
        ''' Deletes all search results
        :param imdbid: str imdb id # <optional>

        Be careful with this one. Supplying an imdbid deletes search results for that
            movie. If you do not supply an imdbid it purges FOR ALL MOVIES.

        BE CAREFUL.

        Returns Bool
        '''

        TABLE = u'SEARCHRESULTS'

        if imdbid:
            command = u'DELETE FROM {} WHERE imdbid="{}"'.format(TABLE, imdbid)
        else:
            command = u'DELETE FROM {}'.format(TABLE)

        if self.execute(command):
            return True
        else:
            return False

    def get_distinct(self, TABLE, column, idcol, idval):
        ''' Gets unique values in TABLE
        :param TABLE: str table name
        :param column: str column to return
        :param idcol: str identifying column
        :param idval: str identifying value

        Gets values in TABLE:column where idcol == idval

        Returns list ['val1', 'val2', 'val3']
        '''

        logging.info(u'Getting distinct values for {} in {}'.format(idval, TABLE))

        command = u'SELECT DISTINCT {} FROM {} WHERE {}="{}"'.format(column, TABLE, idcol, idval)

        data = self.execute(command)

        if data:
            data = data.fetchall()

            if len(data) == 0:
                return None

            lst = []
            for i in data:
                lst.append(i[column])
            return lst
        else:
            logging.error(u'EXECUTE SQL.GET_DISTINCT FAILED.')
            return False

    def row_exists(self, TABLE, imdbid='', guid='', downloadid=''):
        ''' Checks if row exists in table
        :param TABLE: str name of sql table to look through
        :param imdbid: str imdb identification number <optional>
        :param guid: str download guid <optional>
        :param downloadid: str downloader id <optional>

        Checks TABLE for imdbid, guid, or downloadid.
        Exactly one optional variable must be supplied.

        Used to check if we need to add row or update existing row.

        Returns Bool of found status
        '''

        if imdbid:
            idcol = u'imdbid'
            idval = imdbid
        elif guid:
            idcol = u'guid'
            idval = guid
        elif downloadid:
            idcol = u'downloadid'
            idval = downloadid

        else:
            return 'ID ERROR'

        command = u'SELECT 1 FROM {} WHERE {}="{}"'.format(TABLE, idcol, idval)

        row = self.execute(command)

        if row is False or row.fetchone() is None:
            return False
        else:
            return True

    def get_single_search_result(self, idcol, idval):
        ''' Gets single search result
        :param idcol: str identifying column
        :param idval: str identifying value

        Finds in SEARCHRESULTS a row where idcol == idval

        Returns dict
        '''

        logging.info(u'Retreving search result details for {}.'.format(idval))

        command = u'SELECT * FROM SEARCHRESULTS WHERE {}="{}"'.format(idcol, idval)

        result = self.execute(command)

        if result:
            return result.fetchone()
        else:
            return False

    def _get_existing_schema(self):
        table_dict = {}

        # get list of tables in db:
        command = 'SELECT name FROM sqlite_master WHERE type="table"'
        tables = self.execute(command)

        table_dict = {}

        if not tables:
            return False

        for i in tables:
            i = i[0]
            command = u'PRAGMA table_info({})'.format(i)
            columns = self.execute(command)
            if not columns:
                continue
            tmp_dict = {}
            for col in columns:
                tmp_dict[col['name']] = col['type']
            table_dict[i] = tmp_dict

        return table_dict

    def _get_intended_schema(self):
        d = {}
        for table in self.metadata.tables.keys():
            selftable = getattr(self, table)
            d2 = {}
            for i in selftable.c:
                d2[i.name] = str(i.type)
            d[table] = d2
        return d

    def update_tables(self):

        existing = self._get_existing_schema()
        intended = self._get_intended_schema()

        diff = Comparisons.compare_dict(intended, existing)

        if not diff:
            return True

        print 'Database update required. This may take some time.'

        backup_dir = os.path.join(core.PROG_PATH, 'db')
        logging.info(u'Backing up database to {}.'.format(backup_dir))
        print u'Backing up database to {}.'.format(backup_dir)
        try:
            if not os.path.isdir(backup_dir):
                os.mkdir(backup_dir)
            backup = u'{}.{}'.format(core.DB_FILE, datetime.date.today())
            shutil.copyfile(core.DB_FILE, os.path.join(backup_dir, backup))
        except Exception, e: # noqa
            print 'Error backing up database.'
            logging.error(u'Copying SQL DB.', exc_info=True)
            raise

        logging.info(u'Modifying tables.')
        print 'Modifying tables.'

        '''
        For each item in diff, create new column.
        Then, if the new columns name is in self.convert_names, copy data from old column
        Create the new table, then copy data from TMP table
        '''
        for table, schema in diff.iteritems():
            logging.info(u'Modifying table {}'.format(table))
            print u'Modifying table {}'.format(table)
            for name, kind in schema.iteritems():
                command = u'ALTER TABLE {} ADD COLUMN {} {}'.format(table, name, kind)

                self.execute(command)

                if table in self.convert_names.keys():
                    for pair in self.convert_names[table]:
                        if pair[0] == name:
                            command = u'UPDATE {} SET {} = {}'.format(table, pair[0], pair[1])
                            self.execute(command)

            # move TABLE to TABLE_TMP
            table_tmp = u'{}_TMP'.format(table)
            logging.info(u'Renaming table to {}'.format(table_tmp))
            print u'Renaming table to {}'.format(table_tmp)
            command = u'ALTER TABLE {} RENAME TO {}'.format(table, table_tmp)
            self.execute(command)

            # create new table
            logging.info(u'Creating new table {}'.format(table))
            print u'Creating new table {}'.format(table)
            table_meta = getattr(self, table)
            table_meta.create(self.engine)

            # copy data over
            logging.info(u'Merging data from {} to {}'.format(table_tmp, table))
            print u'Merging data from {} to {}'.format(table_tmp, table)
            names = u', '.join(intended[table].keys())
            command = u'INSERT INTO {} ({}) SELECT {} FROM {}'.format(table, names, names, table_tmp)
            self.execute(command)

            logging.info(u'Dropping table {}'.format(table_tmp))
            print u'Dropping table {}'.format(table_tmp)
            command = u'DROP TABLE {}'.format(table_tmp)
            self.execute(command)

            logging.info(u'Finished updating table {}'.format(table))
            print u'Finished updating table {}'.format(table)

        logging.info(u'Database updated')
        print 'Database updated.'

# pylama:ignore=W0401
