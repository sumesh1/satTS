import pandas as pd
import gippy
import os
import re
import numpy as np
from keras.utils.np_utils import to_categorical
import random


def random_ts_samples(file_path, n_samples, seed=None):

    # CSV files containing time-series' to be samples
    ts_files = [file_path + '/' + file for file in os.listdir(file_path) if not file.startswith('.')]

    np.random.seed(seed)

    # Sample each dataframe corresponding to a land cover class, store in list
    dfs = []
    for file in ts_files:
        df = pd.read_csv(file)
        g = df.groupby('pixel')
        a = np.arange(g.ngroups)
        np.random.shuffle(a)
        s = df[g.ngroup().isin(a[:n_samples])]

        dfs.append(s)

    # Convert list to single sample dataframe, convert to same shape as cluster results
    lc_samples = pd.concat(dfs)
    lc_samples = lc_samples.rename(columns={'lc': 'label', 'array_ind': 'array_index'})
    lc_samples = lc_samples.pivot_table(index=['array_index', 'label', 'pixel'], columns='date', values='ndvi').reset_index()

    return lc_samples


def get_training_data(asset_dir, asset_dict, samples_df):

    # Array indices corresponding to sample locations in
    ind = list(samples_df.array_index)
    ind = [elem.strip('()').split(',') for elem in ind]
    ind = [list(map(int, elem)) for elem in ind]
    sample_ind = np.array([*ind])

    # Class labels
    labels = samples_df.label

    # Full file-path for every asset in `fp` (directory structure = default output of sat-search)
    file_paths = []
    for path, subdirs, files in os.walk(asset_dir):
        for name in files:
            # Address .DS_Store file issue
            if not name.startswith('.'):
                file_paths.append(os.path.join(path, name))

    # Scene dates
    dates = [re.findall('\d\d\d\d-\d\d-\d\d', f) for f in file_paths]
    dates = [date for sublist in dates for date in sublist]

    # Asset (band) names
    pattern = '[^_.]+(?=\.[^_.]*$)'
    bands = [re.search(pattern, f).group(0) for f in file_paths]

    # Match band names
    bands = [asset_dict.get(band, band) for band in bands]

    samples_list = []
    for i in range(0, len(file_paths)):

        img = gippy.GeoImage.open(filenames=[file_paths[i]], bandnames=[bands[i]], nodata=0, gain=0.0001)
        bandvals = img.read()

        # Extract values at sample indices for band[i] in time-step[i]
        sample_values = bandvals[sample_ind[:, 0], sample_ind[:, 1]]

        # Store extracted band values as dataframe
        d = {'feature': bands[i],
             'value': sample_values,
             'date': dates[i],
             'label': labels,
             'ind': [*sample_ind]}

        # Necessary due to varying column lengths
        samp = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in d.items()])).ffill()
        samples_list.append(samp)

    # Combine all samples into single, long-form dataframe
    training = pd.concat(samples_list)

    # Reshape for time-series generation
    training['ind'] = tuple(list(training['ind']))
    training = training.sort_values(by=['ind', 'date'])

    return training


def format_training_data(training_data, one_hot=True, shuffle=True, seed=None):

    np.random.seed(seed)
    # Shuffle data
    if shuffle:
        groups = [df for _, df in training_data.groupby(['date', 'ind', 'feature'])]
        random.shuffle(groups)
        training_data = pd.concat(groups).reset_index(drop=True)

    # Create 3D numpy array from sample values
    i = training_data.set_index(['date', 'ind', 'feature'])
    shape = list(map(len, i.index.levels))
    arr = np.full(shape, np.nan)
    arr[i.index.labels] = i.values[:, 0].flat

    # Kereas LSTM shape: [n_samples, n_timesteps, n_feaures]
    x = arr.swapaxes(0, 1)

    # Data labels (Y values); first encode labels as int
    training_data['label'] = training_data['label'].astype('category')

    # TODO: This is not working. Figure out how to return codes for Y labels
    label_codes = training_data['label'].cat.codes

    # Convert labels to int
    training_data['label'] = training_data['label'].cat.codes.astype('str').astype('int')

    group = training_data.groupby('ind')

    y = group.apply(lambda x: x['label'].unique())
    y = y.apply(pd.Series)
    y = y[0].values

    if one_hot:
        y = to_categorical(y, num_classes=len(training_data['label'].unique()))

    return label_codes, x, y
